"""
Train and evaluate the days-until-failure model.

Reads GOLD.FEATURES_RUL from Snowflake (or a local CSV with --csv for offline tests),
trains gradient boosting with a strict time split, and compares it with
(1) a constant guess and (2) the existing rule thresholds used as alarms.

Run from the project root:   python train_rul.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

CAP_DAYS = 7        # remaining life is capped at 7 days ("7 or more")
ALERT_DAYS = 3      # alert when predicted life is under 3 days

SENSOR_FEATURES = [
    'machine_group',
    'vib_mean_1h', 'vib_mean_6h', 'vib_mean_24h', 'vib_std_6h', 'vib_trend',
    'vib_ratio_to_normal',
    'temp_mean_1h', 'temp_mean_6h', 'temp_mean_24h', 'temp_trend', 'temp_above_normal',
    'power_mean_6h', 'degradation_flags_24h',
]
WITH_REPAIR = SENSOR_FEATURES + ['days_since_repair']


def load(csv_path):
    if csv_path:
        df = pd.read_csv(csv_path, parse_dates=['reading_timestamp', 'next_failure_ts'])
    else:
        sys.path.insert(0, 'src')
        from snowflake_loader import connect
        conn = connect()
        cur = conn.cursor()
        cur.execute("USE ROLE INDUSTRIAL_READER")
        cur.execute("USE WAREHOUSE INDUSTRIAL_WH")
        cur.execute("SELECT * FROM INDUSTRIAL_LAKEHOUSE.GOLD.FEATURES_RUL")
        df = cur.fetch_pandas_all()
        conn.close()
        df.columns = [c.lower() for c in df.columns]
    num = [c for c in df.columns if c not in
           ('reading_timestamp', 'machine_id', 'machine_group', 'next_failure_ts', 'split')]
    df[num] = df[num].apply(pd.to_numeric, errors='coerce')
    df['machine_group'] = df['machine_group'].astype('category')
    return df


def add_labels(df):
    """Cap the target and decide which rows have a trustworthy label."""
    cap = pd.Timedelta(days=CAP_DAYS)
    data_end = df.reading_timestamp.max()
    cutoff = df.loc[df.split == 'TEST', 'reading_timestamp'].min()

    df['y'] = np.minimum(df.rul_days.fillna(np.inf), CAP_DAYS)
    ts, nf = df.reading_timestamp, df.next_failure_ts

    # Train: the label may not look into the test period.
    train_ok = (df.split == 'TRAIN') & ((nf < cutoff) | (ts + cap <= cutoff))
    # Test: label known if a failure follows, or if 7 quiet days are inside the data.
    test_ok = (df.split == 'TEST') & (nf.notna() | (ts + cap <= data_end))
    df['label_ok'] = train_ok | test_ok
    return df


def fit(train, features):
    m = HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=24,
        min_samples_leaf=100, categorical_features='from_dtype', random_state=0)
    m.fit(train[features], train.y)
    return m


def alert_scores(test, alert):
    """Reading-level precision/recall plus how many failures got an alert in time."""
    pos = test.y <= ALERT_DAYS
    tp = int((alert & pos).sum())
    prec = tp / max(int(alert.sum()), 1)
    rec = tp / max(int(pos.sum()), 1)

    caught, leads, events = 0, [], 0
    t = test.assign(alert=alert.values)
    for (_, nf), g in t[t.next_failure_ts.notna()].groupby(['machine_id', 'next_failure_ts']):
        events += 1
        window = g[(g.next_failure_ts - g.reading_timestamp) <= pd.Timedelta(days=ALERT_DAYS)]
        hit = window[window.alert]
        if len(hit):
            caught += 1
            leads.append((nf - hit.reading_timestamp.min()).total_seconds() / 86400)
    lead = float(np.median(leads)) if leads else float('nan')
    return prec, rec, caught, events, lead


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', help='local features CSV instead of Snowflake')
    args = ap.parse_args()

    df = add_labels(load(args.csv))
    train = df[(df.split == 'TRAIN') & df.label_ok]
    test = df[(df.split == 'TEST') & df.label_ok]
    print(f"train rows {len(train)}  test rows {len(test)}  (target capped at {CAP_DAYS} days)")

    results, models = [], {}
    const = pd.Series(train.y.mean(), index=test.index)
    results.append(('constant guess', mean_absolute_error(test.y, const),
                    mean_absolute_error(test.y[test.y <= ALERT_DAYS], const[test.y <= ALERT_DAYS])))

    for name, feats in [('model, sensors only', SENSOR_FEATURES),
                        ('model, + days since repair', WITH_REPAIR)]:
        m = fit(train, feats)
        models[name] = (m, feats)
        pred = pd.Series(np.clip(m.predict(test[feats]), 0, CAP_DAYS), index=test.index)
        near = test.y <= ALERT_DAYS
        results.append((name, mean_absolute_error(test.y, pred),
                        mean_absolute_error(test.y[near], pred[near])))
        test = test.assign(**{name: pred})

    print("\nAverage error in days (lower is better)")
    print(f"{'':32s}{'all test rows':>15s}{'rows < 3 days':>15s}")
    for n, a, b in results:
        print(f"{n:32s}{a:15.2f}{b:15.2f}")

    print(f"\nAlarm quality: failure within {ALERT_DAYS} days")
    print(f"{'':32s}{'precision':>10s}{'recall':>8s}{'caught':>10s}{'median lead':>13s}")
    alerts = {
        'rule: degradation flag 24h': test.degradation_flags_24h > 0,
        'rule: flag or temp > 100': (test.degradation_flags_24h > 0) | (test.temp_mean_24h > 100),
    }
    for n in models:
        alerts[f'{n} (<{ALERT_DAYS}d)'] = test[n] < ALERT_DAYS
    for n, a in alerts.items():
        p, r, c, e, lead = alert_scores(test, a)
        print(f"{n:32s}{p:10.2f}{r:8.2f}{c:6d}/{e:<3d}{lead:11.1f} d")

    os.makedirs('models', exist_ok=True)
    import joblib
    for n, (m, feats) in models.items():
        joblib.dump({'model': m, 'features': feats, 'cap_days': CAP_DAYS},
                    f"models/rul_{'with_repair' if 'repair' in n else 'sensors'}.joblib")
    print("\nmodels saved in models/")


if __name__ == '__main__':
    main()

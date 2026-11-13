"""
Builds the demo database from the 30-day simulated history.

What it does, in order:
  1. Runs your normal Silver and Gold code on data/backfill_sensors.csv, so
     silver_telemetry and gold_operations_status describe the history (the
     newest 24 hours of it), not 12 seconds of random readings.
  2. Writes machine_history: one row per machine per hour, with sensor
     averages, the model's predicted days left, the actual days left, and the
     simulator's hidden wear (for the chart only, the model never sees it).
  3. Writes failure_events: every simulated failure with its time.
  4. Writes rul_status: the newest prediction per machine and its priority,
     with the same bands as the Snowflake view GOLD_PREDICTIVE_STATUS.

Predictions come from Snowflake (GOLD.RUL_PREDICTIONS, role INDUSTRIAL_READER)
or from a CSV (--predictions-csv) with the columns READING_TIMESTAMP,
MACHINE_ID, PREDICTED_RUL_DAYS, MODEL_VERSION.

Run from the project root:
    python build_demo_db.py
    python build_demo_db.py --predictions-csv data/predictions.csv

It REPLACES silver_telemetry and gold_operations_status in
factory_lakehouse.db. All data is simulated.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

CAP_DAYS = 7                  # same cap as the model target
WARMING_UP_HOURS = 6          # newest prediction older than this: machine was just repaired
BANDS = [(1.5, "URGENT"), (3.0, "SOON"), (5.0, "WATCH")]   # days left; else OK


# Simulated sensor dropouts, so the Pipeline Health page has something to measure.
# A dropout is a stretch of readings where ONE sensor sends nothing (NULL).
# Four machines have flaky links, the rest drop out now and then. The score on
# the page is then MEASURED from these rows by data_governance.py, nothing is
# typed in. Rows with a failure spike are left alone so failure counts stay true.
FLAKY_MACHINES = ["HEAT_EXCHANGER_02", "PUMP_04", "MOTOR_03", "TURBINE_03"]
BASE_DROPOUT, FLAKY_DROPOUT = 0.09, 0.45      # share of readings affected
MEAN_BURST = 12                               # readings per dropout (2 hours)


def add_sensor_dropouts(sensors, seed=7):
    rng = np.random.default_rng(seed)
    out = sensors.copy()
    cols = ["vibration_rms", "temp_c", "power_kw"]
    for m, idx in out.groupby("machine_id").groups.items():
        rate = FLAKY_DROPOUT if m in FLAKY_MACHINES else BASE_DROPOUT
        pos = out.index.get_indexer(idx)
        starts = np.flatnonzero(rng.random(len(pos)) < rate / MEAN_BURST)
        for st in starts:
            length = int(rng.integers(3, 2 * MEAN_BURST - 2))
            col = cols[int(rng.integers(len(cols)))]
            rows = pos[st:st + length]
            rows = rows[~out["failure_spike"].to_numpy()[rows]]
            out.iloc[rows, out.columns.get_loc(col)] = np.nan
    return out


def load_predictions(csv_path):
    if csv_path:
        p = pd.read_csv(csv_path, parse_dates=["READING_TIMESTAMP"])
    else:
        sys.path.insert(0, "src")
        from snowflake_loader import connect
        conn = connect()
        cur = conn.cursor()
        cur.execute("USE ROLE INDUSTRIAL_READER")
        cur.execute("USE WAREHOUSE INDUSTRIAL_WH")
        cur.execute("SELECT READING_TIMESTAMP, MACHINE_ID, PREDICTED_RUL_DAYS, MODEL_VERSION "
                    "FROM INDUSTRIAL_LAKEHOUSE.GOLD.RUL_PREDICTIONS")
        p = cur.fetch_pandas_all()
        conn.close()
    p.columns = [c.lower() for c in p.columns]
    p["reading_timestamp"] = pd.to_datetime(p["reading_timestamp"])
    return p


def priority(days):
    for limit, name in BANDS:
        if days < limit:
            return name
    return "OK"


def build_history(sensors, preds, truth):
    s = sensors.copy()
    s["machine_type"] = s["machine_id"].str.rsplit("_", n=1).str[0]
    s["hour"] = s["timestamp"].dt.floor("h")
    s["failure_spike"] = s["failure_spike"].astype(bool)
    s["degradation"] = s["degradation"].astype(bool)

    h = (s.groupby(["machine_id", "machine_type", "hour"])
          .agg(vibration_avg=("vibration_rms", "mean"), temp_avg=("temp_c", "mean"),
               power_avg=("power_kw", "mean"), readings=("vibration_rms", "size"),
               failure=("failure_spike", "max"), degradation_readings=("degradation", "sum"))
          .reset_index())
    h["failure"] = h["failure"].astype(int)

    # predicted days left: the last prediction inside each hour
    p = preds.copy()
    p["hour"] = p["reading_timestamp"].dt.floor("h")
    p = (p.sort_values("reading_timestamp").groupby(["machine_id", "hour"]).tail(1)
          [["machine_id", "hour", "predicted_rul_days"]])
    h = h.merge(p, on=["machine_id", "hour"], how="left")

    # actual days left: time to the next failure, capped, unknown when not observable
    data_end = s["timestamp"].max()
    events = s[s["failure_spike"]].groupby("machine_id")["timestamp"].apply(lambda x: np.sort(x.values))
    actual = np.full(len(h), np.nan)
    for m, idx in h.groupby("machine_id").groups.items():
        ends = (h.loc[idx, "hour"] + pd.Timedelta(hours=1)).values
        ev = events.get(m, np.array([], dtype="datetime64[ns]"))
        pos = np.searchsorted(ev, ends, side="left")
        for i, k, e in zip(idx, pos, ends):
            if k < len(ev):
                actual[h.index.get_loc(i)] = (ev[k] - e) / np.timedelta64(1, "D")
            elif (data_end - pd.Timestamp(e)) >= pd.Timedelta(days=CAP_DAYS):
                actual[h.index.get_loc(i)] = CAP_DAYS
    h["actual_rul_days"] = np.minimum(actual, CAP_DAYS)

    if truth is not None:
        t = truth.copy()
        t["hour"] = t["timestamp"].dt.floor("h")
        t = t.groupby(["machine_id", "hour"], as_index=False)["wear"].mean().rename(columns={"wear": "true_wear"})
        h = h.merge(t, on=["machine_id", "hour"], how="left")
    else:
        h["true_wear"] = np.nan

    h["hour"] = h["hour"].dt.strftime("%Y-%m-%d %H:%M:%S")
    for c in ["vibration_avg", "temp_avg", "power_avg", "predicted_rul_days", "actual_rul_days", "true_wear"]:
        h[c] = h[c].round(4)
    h["degradation_readings"] = h["degradation_readings"].astype(int)
    return h, s


def build_status(s, preds):
    last = s.groupby("machine_id")["timestamp"].max().rename("last_reading")
    lp = (preds.sort_values("reading_timestamp").groupby("machine_id").tail(1)
               .set_index("machine_id")
               .rename(columns={"reading_timestamp": "pred_for_reading"}))
    out = pd.concat([last, lp[["pred_for_reading", "predicted_rul_days", "model_version"]]], axis=1)
    out = out.reset_index().rename(columns={"index": "machine_id"})
    gap_h = (out["last_reading"] - out["pred_for_reading"]).dt.total_seconds() / 3600
    warming = out["pred_for_reading"].isna() | (gap_h > WARMING_UP_HOURS)
    out["priority"] = [("WARMING_UP" if w else priority(d))
                       for w, d in zip(warming, out["predicted_rul_days"])]
    out.loc[warming, "predicted_rul_days"] = np.nan
    out["predicted_rul_days"] = out["predicted_rul_days"].round(3)
    for c in ("last_reading", "pred_for_reading"):
        out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out[["machine_id", "last_reading", "pred_for_reading", "predicted_rul_days",
                "priority", "model_version"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensors", default="data/backfill_sensors.csv")
    ap.add_argument("--truth", default="data/backfill_truth.csv")
    ap.add_argument("--predictions-csv")
    ap.add_argument("--prices", default="data/day_ahead_prices.csv", help="hourly prices from load_prices.py")
    ap.add_argument("--no-dropouts", action="store_true", help="skip the simulated sensor dropouts (health score stays 100%%)")
    ap.add_argument("--force", action="store_true", help="continue even if predictions do not match the sensor file")
    args = ap.parse_args()

    sensors = pd.read_csv(args.sensors, parse_dates=["timestamp"])
    truth = (pd.read_csv(args.truth, parse_dates=["timestamp"])
             if os.path.exists(args.truth) else None)
    preds = load_predictions(args.predictions_csv)

    # The predictions must belong to THIS sensor file.
    key = sensors[["machine_id", "timestamp"]].rename(columns={"timestamp": "reading_timestamp"})
    covered = preds.merge(key, on=["machine_id", "reading_timestamp"], how="inner").shape[0] / max(len(preds), 1)
    print(f"predictions: {len(preds)} rows, {covered:.1%} match a reading in {args.sensors}")
    if covered < 1.0:
        m = preds.merge(key, on=["machine_id", "reading_timestamp"], how="left", indicator=True)
        miss = m[m["_merge"] == "left_only"]
        print(f"  {len(miss)} predictions have no reading. Their timestamps run from "
              f"{miss['reading_timestamp'].min()} to {miss['reading_timestamp'].max()}")
        print(f"  the sensor file runs from {sensors['timestamp'].min()} to {sensors['timestamp'].max()}")
        print("  machines with most unmatched rows:", miss["machine_id"].value_counts().head(4).to_dict())
    if covered < 0.99 and not args.force:
        sys.exit("The predictions do not match this sensor file. Use the CSV that was loaded to "
                 "Snowflake, or pass --force.")

    # 0. Real hourly electricity prices, when load_prices.py has been run
    eng = create_engine("sqlite:///factory_lakehouse.db")
    if os.path.exists(args.prices):
        pd.read_csv(args.prices).to_sql("energy_prices", eng, if_exists="replace", index=False)
        print(f"energy_prices: loaded from {args.prices}")
    else:
        print(f"no {args.prices}: run load_prices.py first for real prices (Gold uses the simulated price now)")

    # 1. Silver and Gold from the history, with the normal pipeline code
    sys.path.insert(0, "src")
    import transformer
    import gold_analytics
    silver_input = args.sensors
    if not args.no_dropouts:
        silver_input = "data/_silver_input.csv"
        add_sensor_dropouts(sensors).to_csv(silver_input, index=False)
    tx = transformer.SilverTransformer()
    tx.bronze_path = silver_input
    tx.transform()
    if silver_input != args.sensors:
        os.remove(silver_input)
    gold_analytics.generate_financial_gold()

    # 2-4. history, failure events, prediction status
    hist, s = build_history(sensors, preds, truth)
    events = (s[s["failure_spike"]][["machine_id", "machine_type", "timestamp", "vibration_rms", "temp_c"]]
              .rename(columns={"timestamp": "failure_ts"}).sort_values(["machine_id", "failure_ts"]))
    events["failure_ts"] = events["failure_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    status = build_status(s, preds)

    hist.to_sql("machine_history", eng, if_exists="replace", index=False)
    events.to_sql("failure_events", eng, if_exists="replace", index=False)
    status.to_sql("rul_status", eng, if_exists="replace", index=False)
    with eng.begin() as c:
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_hist ON machine_history (machine_id, hour)"))

    print(f"\nmachine_history: {len(hist)} rows   failure_events: {len(events)}   rul_status: {len(status)}")
    print(f"hours with a prediction: {hist['predicted_rul_days'].notna().mean():.0%}   "
          f"with a known actual: {hist['actual_rul_days'].notna().mean():.0%}")
    print("\npriority now:", status["priority"].value_counts().to_dict())
    print(status.sort_values("predicted_rul_days").head(5).to_string(index=False))
    print(f"\ndatabase size: {os.path.getsize('factory_lakehouse.db') / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

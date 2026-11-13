import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine

engine = create_engine('sqlite:///factory_lakehouse.db')

# Plausible sensor ranges. Same limits as the Snowflake data metric functions.
LIMITS = {
    'vibration_rms': (0, 50),
    'temp_c': (-50, 200),
    'power_kw': (0, 200),
}
HEALTHY_FROM_PERCENT = 95


def compute_quality(eng=engine):
    """Data quality of Silver, kept apart from machine events.

    Data quality asks: is the reading itself usable? (not empty, not
    duplicated, inside a plausible range). A failure spike is not a data
    error. It is a real machine event, so it is reported separately.
    """
    df = pd.read_sql(
        "SELECT timestamp, machine_id, vibration_rms, temp_c, power_kw, "
        "quality_flag FROM silver_telemetry", eng)
    total = len(df)

    cols = ['timestamp', 'machine_id'] + list(LIMITS)
    null_rows = df[cols].isna().any(axis=1)
    dup_rows = df.duplicated(subset=['machine_id', 'timestamp'], keep='first')
    out_of_range = pd.Series(False, index=df.index)
    for col, (lo, hi) in LIMITS.items():
        out_of_range |= (df[col] < lo) | (df[col] > hi)

    bad = null_rows | dup_rows | out_of_range
    score = round((1 - bad.sum() / total) * 100, 2) if total else 0.0

    events = (df.groupby('quality_flag').size()
                .rename('count').reset_index()
                .to_dict('records'))
    event_rows = int((df['quality_flag'] != 'PASS').sum())

    return {
        'rows': int(total),
        'null_rows': int(null_rows.sum()),
        'duplicate_rows': int(dup_rows.sum()),
        'out_of_range_rows': int(out_of_range.sum()),
        'data_quality_score_percent': score,
        'status': 'HEALTHY' if score >= HEALTHY_FROM_PERCENT else 'WARNING',
        'latest_reading': df['timestamp'].max() if total else None,
        'machine_events': events,
        'event_rate_percent': round(event_rows / total * 100, 2) if total else 0.0,
    }


def run_governance_audit():
    print("🛡️ STARTING DATA GOVERNANCE AUDIT...")
    q = compute_quality()

    print("\n📊 DATA QUALITY (is the reading usable?):")
    print(f"   rows checked:        {q['rows']}")
    print(f"   rows with nulls:     {q['null_rows']}")
    print(f"   duplicate rows:      {q['duplicate_rows']}")
    print(f"   out-of-range rows:   {q['out_of_range_rows']}")
    print(f"✅ DATA QUALITY SCORE: {q['data_quality_score_percent']:.2f}%")

    age = (datetime.now() - pd.to_datetime(q['latest_reading'])).total_seconds()
    print(f"\n🕒 LATEST READING: {q['latest_reading']}  ({age / 60:.1f} min ago)")

    print("\n⚙️ MACHINE EVENTS (real events, not data errors):")
    for row in q['machine_events']:
        print(f"   {row['quality_flag']:<20} {row['count']}")
    print(f"   share of readings with an event: {q['event_rate_percent']}%")

    if q['status'] != 'HEALTHY':
        print("⚠️ WARNING: Data quality below threshold. Inspect the sources.")

if __name__ == "__main__":
    run_governance_audit()
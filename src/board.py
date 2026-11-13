"""
Data for the Maintenance board. Reads the tables that build_demo_db.py writes:
rul_status, failure_events and machine_history. All data is simulated.
"""
import pandas as pd
from sqlalchemy import create_engine, text

TRAIN_DAYS = 20      # the model was trained on the first 20 days of the 30-day history


def _engine(engine):
    return engine or create_engine("sqlite:///factory_lakehouse.db")


def _has(eng, table):
    with eng.connect() as c:
        return c.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"),
                         {"t": table}).fetchone() is not None


def maintenance_list(engine=None) -> dict:
    eng = _engine(engine)
    if not _has(eng, "rul_status"):
        raise LookupError("No prediction data. Run build_demo_db.py first.")
    st = pd.read_sql("SELECT * FROM rul_status", eng)
    st["last_reading"] = pd.to_datetime(st["last_reading"])
    last_fail = {}
    if _has(eng, "failure_events"):
        ev = pd.read_sql("SELECT machine_id, MAX(failure_ts) AS t FROM failure_events GROUP BY machine_id", eng)
        last_fail = {r.machine_id: pd.Timestamp(r.t) for r in ev.itertuples()}
    out = []
    for r in st.itertuples():
        t = last_fail.get(r.machine_id)
        ago = int((r.last_reading - t).total_seconds() // 86400) if t is not None else None
        rul = None if pd.isna(r.predicted_rul_days) else round(float(r.predicted_rul_days), 2)
        out.append({"machine_id": r.machine_id, "predicted_rul_days": rul,
                    "priority": r.priority, "last_failure_days_ago": ago})
    return {"machines": out}


def machine_history(machine_id: str, engine=None) -> dict:
    eng = _engine(engine)
    if not _has(eng, "machine_history"):
        raise LookupError("No history data. Run build_demo_db.py first.")
    df = pd.read_sql("SELECT hour, predicted_rul_days, actual_rul_days FROM machine_history WHERE machine_id = :m",
                     eng, params={"m": machine_id})
    if df.empty:
        raise LookupError(f"No history for {machine_id}")
    df["day"] = pd.to_datetime(df["hour"]).dt.normalize()
    daily = df.groupby("day").agg(t=("actual_rul_days", "mean"), p=("predicted_rul_days", "mean")).reset_index()
    days = []
    for i, r in enumerate(daily.itertuples(), start=1):
        days.append({"day": i,
                     "true_days_left": None if pd.isna(r.t) else round(float(r.t), 2),
                     "predicted_days_left": None if pd.isna(r.p) else round(float(r.p), 2)})
    return {"machine_id": machine_id, "days": days,
            "train_days": TRAIN_DAYS if len(days) > TRAIN_DAYS else None}

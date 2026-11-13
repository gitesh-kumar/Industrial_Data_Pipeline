import os
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import board  # noqa: E402


def make(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'b.sqlite'}")
    pd.DataFrame([("PUMP_02", "2026-11-12 18:00:00", "2026-11-12 18:00:00", 1.2, "URGENT", "v1"),
                  ("MOTOR_01", "2026-11-12 18:00:00", None, None, "WARMING_UP", "v1")],
                 columns=["machine_id", "last_reading", "pred_for_reading", "predicted_rul_days",
                          "priority", "model_version"]).to_sql("rul_status", eng, index=False)
    pd.DataFrame([("PUMP_02", "PUMP", "2026-11-10 06:00:00", 1.0, 1.0, 1.0)],
                 columns=["machine_id", "machine_type", "failure_ts", "a", "b", "c"]).to_sql(
        "failure_events", eng, index=False)
    hours = pd.date_range("2026-10-14", periods=30 * 24, freq="h")
    pd.DataFrame({"machine_id": "PUMP_02", "hour": hours.strftime("%Y-%m-%d %H:%M:%S"),
                  "predicted_rul_days": 3.0, "actual_rul_days": 2.0}).to_sql("machine_history", eng, index=False)
    return eng


def test_maintenance_list(tmp_path):
    r = board.maintenance_list(make(tmp_path))["machines"]
    p = {m["machine_id"]: m for m in r}
    assert p["PUMP_02"]["priority"] == "URGENT" and p["PUMP_02"]["predicted_rul_days"] == 1.2
    assert p["PUMP_02"]["last_failure_days_ago"] == 2
    assert p["MOTOR_01"]["predicted_rul_days"] is None and p["MOTOR_01"]["last_failure_days_ago"] is None


def test_history_is_daily_with_train_boundary(tmp_path):
    h = board.machine_history("PUMP_02", make(tmp_path))
    assert len(h["days"]) == 30 and h["train_days"] == 20
    assert h["days"][0] == {"day": 1, "true_days_left": 2.0, "predicted_days_left": 3.0}


def test_missing_tables_and_machines(tmp_path):
    empty = create_engine(f"sqlite:///{tmp_path / 'e.sqlite'}")
    with pytest.raises(LookupError):
        board.maintenance_list(empty)
    with pytest.raises(LookupError):
        board.machine_history("PUMP_02", empty)
    with pytest.raises(LookupError):
        board.machine_history("NOPE_01", make(tmp_path))

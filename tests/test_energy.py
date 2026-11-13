import os
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import energy_costs          # noqa: E402
from load_prices import to_hourly   # noqa: E402


def make_db(tmp_path, readings, prices=None):
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    pd.DataFrame(readings, columns=["machine_id", "machine_type", "timestamp", "power_kw"]).to_sql(
        "silver_telemetry", eng, index=False)
    if prices is not None:
        pd.DataFrame(prices, columns=["hour", "price_eur_mwh"]).to_sql("energy_prices", eng, index=False)
    return eng


# ---- load_prices.to_hourly -------------------------------------------------
def test_quarter_hours_are_averaged_per_berlin_hour():
    # 2026-11-10 00:00 Berlin = 2026-11-09 23:00 UTC. Eight quarter hours = two hours.
    start = int(pd.Timestamp("2026-11-09 23:00", tz="UTC").timestamp())
    secs = [start + 900 * i for i in range(8)]
    out = to_hourly(secs, [10, 20, 30, 40, 100, 100, 100, 100])
    assert list(out["hour"]) == ["2026-11-10 00:00:00", "2026-11-10 01:00:00"]
    assert list(out["price_eur_mwh"]) == [25.0, 100.0]


def test_missing_prices_are_skipped_and_negative_prices_kept():
    start = int(pd.Timestamp("2026-11-09 23:00", tz="UTC").timestamp())
    out = to_hourly([start, start + 900, start + 3600], [None, -10.0, 5.0])
    assert list(out["price_eur_mwh"]) == [-10.0, 5.0]


def test_hour_that_repeats_when_clocks_go_back_appears_once():
    # 2026-10-25: 03:00 CEST goes back to 02:00 CET. 02:00-03:00 happens twice.
    start = int(pd.Timestamp("2026-10-24 22:00", tz="UTC").timestamp())    # 00:00 Berlin
    secs = [start + 3600 * i for i in range(6)]
    out = to_hourly(secs, [1, 2, 3, 4, 5, 6])
    assert out["hour"].is_unique


# ---- energy_costs ------------------------------------------------------------
def hourly_rows(machine, mtype, day, kws):
    return [(machine, mtype, f"{day} {h:02d}:{m:02d}:00", kw)
            for h, kw in enumerate(kws) for m in (0, 30)]


def test_cost_is_kwh_times_price_and_only_consumers_count(tmp_path):
    readings = (hourly_rows("PUMP_01", "PUMP", "2026-11-10", [10, 20])
                + hourly_rows("TURBINE_01", "TURBINE", "2026-11-10", [50, 50])
                + hourly_rows("GENERATOR_01", "GENERATOR", "2026-11-10", [90, 90]))
    prices = [("2026-11-10 00:00:00", 100.0), ("2026-11-10 01:00:00", 200.0)]
    r = energy_costs.compute_energy(make_db(tmp_path, readings, prices))
    # 10 kW for 1 h at 100 EUR/MWh = 1.00 EUR, 20 kW at 200 = 4.00 EUR
    assert r["cost_24h_eur"] == pytest.approx(5.0)
    assert r["cost_30d_eur"] == pytest.approx(5.0)
    assert [m["machine_id"] for m in r["machines"]] == ["PUMP_01"]
    assert len(r["hours"]) == 24
    assert r["hours"][-1]["price_eur_mwh"] == 200.0 and r["hours"][-1]["cost_eur"] == pytest.approx(4.0)
    assert r["readings_shifted_days"] == 0


def test_negative_price_gives_negative_cost(tmp_path):
    readings = hourly_rows("MOTOR_01", "MOTOR", "2026-11-10", [10])
    r = energy_costs.compute_energy(make_db(tmp_path, readings, [("2026-11-10 00:00:00", -50.0)]))
    assert r["cost_24h_eur"] == pytest.approx(-0.5)


def test_old_simulated_readings_are_matched_to_the_same_weekday_and_hour(tmp_path):
    # readings in January, real prices in November: shifted by whole weeks
    readings = hourly_rows("PUMP_01", "PUMP", "2026-01-05", [10])          # a Monday, 00:00
    price_days = pd.date_range("2026-10-13", "2026-11-12 23:00", freq="h")
    prices = [(h.strftime("%Y-%m-%d %H:%M:%S"), 100.0 + h.hour) for h in price_days]
    r = energy_costs.compute_energy(make_db(tmp_path, readings, prices))
    assert r["readings_shifted_days"] % 7 == 0 and r["readings_shifted_days"] > 0
    assert r["hours"][-1]["price_eur_mwh"] == 100.0                       # hour 0 of a price day
    assert r["hours_without_price"] == 0


def test_without_prices_nothing_breaks(tmp_path):
    eng = make_db(tmp_path, hourly_rows("PUMP_01", "PUMP", "2026-11-10", [10]))
    assert energy_costs.has_prices(eng) is False
    assert energy_costs.latest_price(eng) is None
    with pytest.raises(LookupError):
        energy_costs.compute_energy(eng)


def test_latest_price_is_the_price_of_the_newest_hour(tmp_path):
    readings = hourly_rows("PUMP_01", "PUMP", "2026-11-10", [10, 10])
    eng = make_db(tmp_path, readings, [("2026-11-10 00:00:00", 70.0), ("2026-11-10 01:00:00", 95.0)])
    assert energy_costs.latest_price(eng) == 95.0


def test_api_returns_404_without_prices_and_json_with_prices(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    (tmp_path / "static").mkdir()
    monkeypatch.chdir(tmp_path)
    if "api" in sys.modules:
        del sys.modules["api"]
    import api
    client = TestClient(api.app)
    eng = create_engine("sqlite:///factory_lakehouse.db")
    pd.DataFrame(hourly_rows("PUMP_01", "PUMP", "2026-11-10", [10]),
                 columns=["machine_id", "machine_type", "timestamp", "power_kw"]).to_sql("silver_telemetry", eng, index=False)
    assert client.get("/energy").status_code == 404
    pd.DataFrame([("2026-11-10 00:00:00", 100.0)], columns=["hour", "price_eur_mwh"]).to_sql("energy_prices", eng, index=False)
    body = client.get("/energy").json()
    assert body["cost_24h_eur"] == 1.0 and len(body["hours"]) == 24
    eng.dispose()

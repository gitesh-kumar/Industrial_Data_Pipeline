"""
Builds tests/eval.db: a frozen test database for the assistant evaluation.

Why a separate database: the live pipeline produces random, mostly healthy
data, so many questions would have an empty answer ("no machine needs
maintenance"). That tests nothing. This script runs the REAL pipeline code
(ingestion generator, transformer, gold_analytics) on a seeded fixture and
adds a few known problems, so every kind of answer exists:

  COMPRESSOR_03   runs far too hot          -> CRITICAL, IMMEDIATE_SHUTDOWN
  PUMP_02         runs hot                  -> WARNING
  GENERATOR_02    runs hot                  -> WARNING, REDUCE_LOAD (at the fixed price)
  TURBINE_01      six extra failure spikes  -> SCHEDULE_MAINTENANCE
  MOTOR_03        eight extra degradation flags
The random 5 percent spikes of the simulator add a few more maintenance cases.

Run from the project root:   python tests/build_eval_db.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
OUT = os.path.join(ROOT, "tests", "eval.db")

STEPS = 60                      # readings per machine, 10 minutes apart
START = pd.Timestamp("2026-01-01 00:00:00")
FIXED_PRICE_EUR_MWH = 240.0     # peak price, so WARNING machines get REDUCE_LOAD


def make_bronze() -> pd.DataFrame:
    sys.path.insert(0, SRC)
    from ingestion import SmartFactorySimulator

    np.random.seed(7)
    sim = SmartFactorySimulator()
    frames = []
    for i in range(STEPS):
        batch = sim.generate_batch()
        batch["timestamp"] = (START + pd.Timedelta(minutes=10 * i)).strftime("%Y-%m-%d %H:%M:%S")
        frames.append(batch)
    df = pd.concat(frames, ignore_index=True)

    def rows(machine):
        return df["machine_id"] == machine

    df.loc[rows("COMPRESSOR_03"), "temp_c"] += 40
    df.loc[rows("PUMP_02"), "temp_c"] += 30
    df.loc[rows("GENERATOR_02"), "temp_c"] += 22

    idx = df[rows("TURBINE_01")].index[10:16]
    df.loc[idx, "failure_spike"] = True
    df.loc[idx, "vibration_rms"] *= 3

    idx = df[rows("MOTOR_03")].index[20:28]
    df.loc[idx, "degradation"] = True
    return df


def main():
    work = tempfile.mkdtemp()
    os.makedirs(os.path.join(work, "data"))
    make_bronze().to_csv(os.path.join(work, "data", "bronze_sensors.csv"), index=False)

    cwd = os.getcwd()
    os.chdir(work)
    try:
        import energy_api
        energy_api.EnergyMarketAPI.get_current_price = lambda self: {
            "timestamp": "fixture", "unit": "EUR/MWh", "price": FIXED_PRICE_EUR_MWH}
        import transformer
        import gold_analytics
        transformer.SilverTransformer().transform()
        gold_analytics.generate_financial_gold()
        shutil.copy("factory_lakehouse.db", OUT)
    finally:
        os.chdir(cwd)
        shutil.rmtree(work, ignore_errors=True)
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()

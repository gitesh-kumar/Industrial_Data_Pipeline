"""
Score every row of GOLD.FEATURES_RUL with the saved model and write the result
to GOLD.RUL_PREDICTIONS (full refresh: truncate, then append).

Run from the project root after train_rul.py:   python score_rul.py
Login: key pair as INDUSTRIAL_LOADER, role INDUSTRIAL_ML.
"""
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

sys.path.insert(0, 'src')
from snowflake_loader import connect  # noqa: E402

MODEL_FILE = 'models/rul_sensors.joblib'
DB, SCHEMA, TABLE = 'INDUSTRIAL_LAKEHOUSE', 'GOLD', 'RUL_PREDICTIONS'


def main():
    bundle = joblib.load(MODEL_FILE)
    model, feats, cap = bundle['model'], bundle['features'], bundle['cap_days']

    conn = connect()
    cur = conn.cursor()
    cur.execute("USE ROLE INDUSTRIAL_ML")
    cur.execute("USE WAREHOUSE INDUSTRIAL_WH")
    cur.execute(f"SELECT * FROM {DB}.{SCHEMA}.FEATURES_RUL")
    df = cur.fetch_pandas_all()
    df.columns = [c.lower() for c in df.columns]

    skip = ('reading_timestamp', 'machine_id', 'machine_group', 'next_failure_ts', 'split')
    num = [c for c in df.columns if c not in skip]
    df[num] = df[num].apply(pd.to_numeric, errors='coerce')
    df['machine_group'] = df['machine_group'].astype('category')

    pred = np.clip(model.predict(df[feats]), 0, cap)
    now = datetime.now().replace(microsecond=0)
    out = pd.DataFrame({
        'READING_TIMESTAMP': df.reading_timestamp,
        'MACHINE_ID': df.machine_id,
        'PREDICTED_RUL_DAYS': np.round(pred, 3),
        'MODEL_VERSION': f"sensors_v1_{now:%Y%m%d}",
        'SCORED_AT': now,
    })

    cur.execute(f"TRUNCATE TABLE {DB}.{SCHEMA}.{TABLE}")
    ok, _, n_rows, _ = write_pandas(
        conn, out, TABLE, database=DB, schema=SCHEMA,
        overwrite=False, auto_create_table=False, use_logical_type=True)
    print(f"scored {len(out)} rows, written: success={ok}, rows={n_rows}")

    latest = out.sort_values('READING_TIMESTAMP').groupby('MACHINE_ID').tail(1)
    print(latest.sort_values('PREDICTED_RUL_DAYS')[
        ['MACHINE_ID', 'READING_TIMESTAMP', 'PREDICTED_RUL_DAYS']].to_string(index=False))
    conn.close()


if __name__ == '__main__':
    main()

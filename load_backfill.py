"""
Load the simulated 30-day history into Snowflake Bronze.

Run from the project root, after wear_simulator.py:
    python load_backfill.py

Uses the existing connect() from src/snowflake_loader.py (key-pair login as
INDUSTRIAL_LOADER). Truncates BRONZE.SENSOR_READINGS and appends the new rows,
so the table object stays the same and the dynamic tables on top keep working.
"""
import sys
import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

sys.path.insert(0, 'src')
from snowflake_loader import connect  # noqa: E402

CSV = 'data/backfill_sensors.csv'
TABLE = 'SENSOR_READINGS'
DB, SCHEMA = 'INDUSTRIAL_LAKEHOUSE', 'BRONZE'


def main():
    df = pd.read_csv(CSV, parse_dates=['timestamp'])
    df = df.rename(columns={'timestamp': 'reading_timestamp'})
    df['loaded_at'] = pd.Timestamp.now().floor('s')
    df.columns = [c.upper() for c in df.columns]        # Snowflake column names
    print(f"read {len(df)} rows from {CSV}")

    conn = connect()
    cur = conn.cursor()
    cur.execute("USE ROLE INDUSTRIAL_INGEST")
    cur.execute("USE WAREHOUSE INDUSTRIAL_WH")

    cur.execute(f"TRUNCATE TABLE {DB}.{SCHEMA}.{TABLE}")
    print("old rows removed")

    ok, n_chunks, n_rows, _ = write_pandas(
        conn, df, TABLE, database=DB, schema=SCHEMA,
        overwrite=False, auto_create_table=False, use_logical_type=True,
    )
    print(f"loaded: success={ok}, rows={n_rows}")

    cur.execute(f"SELECT COUNT(*), MIN(READING_TIMESTAMP), MAX(READING_TIMESTAMP) "
                f"FROM {DB}.{SCHEMA}.{TABLE}")
    print("in Bronze now:", cur.fetchone())
    conn.close()


if __name__ == '__main__':
    main()
import os
import pandas as pd
from dotenv import load_dotenv
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

load_dotenv()


def connect():
    # Logs in with the key pair. No password anywhere.
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"],
        role="INDUSTRIAL_INGEST",
        warehouse="INDUSTRIAL_WH",
        database="INDUSTRIAL_LAKEHOUSE",
        schema="BRONZE",
    )

def load_bronze(csv_path="data/bronze_sensors.csv"):
    """Original loader for the SQLite-track CSV (random spikes, few rows).

    Empties BRONZE.SENSOR_READINGS and loads the CSV. Do not use it after the
    30-day history is loaded: it replaces that history. Use load_backfill.py.
    """
    df = pd.read_csv(csv_path)
    df.columns = [c.upper() for c in df.columns]
    df = df.rename(columns={"TIMESTAMP": "READING_TIMESTAMP"})
    df["READING_TIMESTAMP"] = pd.to_datetime(df["READING_TIMESTAMP"])
    df["LOADED_AT"] = pd.Timestamp.now()

    conn = connect()
    try:
        ok, _, n_rows, _ = write_pandas(
            conn, df,
            table_name="SENSOR_READINGS",
            database="INDUSTRIAL_LAKEHOUSE",
            schema="BRONZE",
            overwrite=True,          # empties the table, then reloads the full CSV
            use_logical_type=True,   # keeps timestamps as timestamps
        )
        print(f"Loaded {n_rows} rows into BRONZE.SENSOR_READINGS (ok={ok})")
    finally:
        conn.close()


if __name__ == "__main__":
    print("This file provides connect(). To load the 30-day history, run: python load_backfill.py")
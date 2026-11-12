-- 01_bronze.sql
-- Raw layer. Role: INDUSTRIAL_INGEST (select it in the role dropdown).
--
-- The sensor table is filled by load_backfill.py (30 days of simulated history)
-- or by src/snowflake_loader.py. Rows are stored exactly as they arrive.
-- Timestamps are local Berlin time without a time zone (TIMESTAMP_NTZ).

USE WAREHOUSE INDUSTRIAL_WH;

CREATE TABLE IF NOT EXISTS INDUSTRIAL_LAKEHOUSE.BRONZE.SENSOR_READINGS (
  READING_TIMESTAMP TIMESTAMP_NTZ,
  MACHINE_ID        STRING,
  MACHINE_TYPE      STRING,
  VIBRATION_RMS     FLOAT,
  TEMP_C            FLOAT,
  POWER_KW          FLOAT,
  FAILURE_SPIKE     BOOLEAN,
  DEGRADATION       BOOLEAN,
  LOADED_AT         TIMESTAMP_NTZ
);

-- One simulated market price, the same value the SQLite demo uses.
CREATE TABLE IF NOT EXISTS INDUSTRIAL_LAKEHOUSE.BRONZE.ENERGY_PRICE (
  PRICE_TIMESTAMP TIMESTAMP_NTZ,
  UNIT            STRING,
  PRICE_EUR_MWH   FLOAT,
  LOADED_AT       TIMESTAMP_NTZ
);

-- Insert only if this price is not there yet, so the file can run twice.
INSERT INTO INDUSTRIAL_LAKEHOUSE.BRONZE.ENERGY_PRICE
SELECT TO_TIMESTAMP_NTZ('2026-04-17 16:10:00'), 'EUR/MWh', 258.81,
       CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
WHERE NOT EXISTS (
  SELECT 1 FROM INDUSTRIAL_LAKEHOUSE.BRONZE.ENERGY_PRICE
  WHERE PRICE_TIMESTAMP = TO_TIMESTAMP_NTZ('2026-04-17 16:10:00')
);
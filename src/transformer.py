import pandas as pd
from sqlalchemy import create_engine

class SilverTransformer:
    def __init__(self):
        self.engine = create_engine('sqlite:///factory_lakehouse.db')
        self.bronze_path = 'data/bronze_sensors.csv'

    def transform(self):
        print("🧹 Cleaning Bronze data for Silver layer...")
        df = pd.read_csv(self.bronze_path)

        # 1. Deduplication: one reading per machine per timestamp
        df = df.drop_duplicates(subset=['machine_id', 'timestamp'], keep='first')

        # 2. Machine type comes from the machine id: TURBINE_01 -> TURBINE,
        #    HEAT_EXCHANGER_02 -> HEAT_EXCHANGER. Older Bronze rows hold
        #    the wrong value here (TURBINE_01), so we always recompute it.
        df['machine_type'] = df['machine_id'].str.rsplit('_', n=1).str[0]

        # 3. Data quality flags. Weakest first, strongest last, so the
        #    strongest flag wins. Same order as the Snowflake Silver table:
        #    FAILURE_SPIKE > DEGRADATION_WARN > VIBRATION_CRITICAL
        #    > HIGH_TEMP_WARN > PASS
        df['quality_flag'] = 'PASS'
        df.loc[df['temp_c'] > 120,         'quality_flag'] = 'HIGH_TEMP_WARN'
        df.loc[df['vibration_rms'] > 10,   'quality_flag'] = 'VIBRATION_CRITICAL'
        df.loc[df['degradation'] == True,  'quality_flag'] = 'DEGRADATION_WARN'
        df.loc[df['failure_spike'] == True,'quality_flag'] = 'FAILURE_SPIKE'

        # 4. Standardization
        df['temp_f'] = (df['temp_c'] * 9/5) + 32

        # 5. Risk score (0-100) based on vibration and temp
        df['risk_score'] = (
            (df['vibration_rms'] / df['vibration_rms'].max() * 60) +
            (df['temp_c'] / df['temp_c'].max() * 40)
        ).round(2)

        df.to_sql('silver_telemetry', self.engine, if_exists='replace', index=False)
        print(f"✅ Silver Layer Updated — {len(df)} records, {df['machine_id'].nunique()} machines.")

if __name__ == "__main__":
    tx = SilverTransformer()
    tx.transform()
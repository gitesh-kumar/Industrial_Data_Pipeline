import pandas as pd
from sqlalchemy import create_engine

class SilverTransformer:
    def __init__(self):
        self.engine = create_engine('sqlite:///factory_lakehouse.db')
        self.bronze_path = 'data/bronze_sensors.csv'

    def transform(self):
        print("🧹 Cleaning Bronze data for Silver layer...")
        df = pd.read_csv(self.bronze_path)

        # 1. Deduplication
        df = df.drop_duplicates()

        # 2. Data Quality Flags
        # Flagging data instead of deleting 
        df['quality_flag'] = 'PASS'
        df.loc[df['temp_c'] > 120, 'quality_flag'] = 'HIGH_TEMP_WARN'
        df.loc[df['vibration_rms'] > 10, 'quality_flag'] = 'VIBRATION_CRITICAL'
        
        # 3. Standardization
        df['temp_f'] = (df['temp_c'] * 9/5) + 32

        # Load to Silver Table in SQL
        df.to_sql('silver_telemetry', self.engine, if_exists='replace', index=False)
        print("Silver Layer Updated.")

if __name__ == "__main__":
    tx = SilverTransformer()
    tx.transform()
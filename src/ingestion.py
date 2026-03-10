import pandas as pd
import numpy as np
import time
import os
from datetime import datetime

class SmartFactorySimulator:
    def __init__(self):
        self.machines = ['TURBINE_01', 'PUMP_07', 'COMPRESSOR_03']
        self.data_path = 'data/bronze_sensors.csv'
        if not os.path.exists('data'): os.makedirs('data')

    def generate_batch(self):
        records = []
        for m in self.machines:
            # Physics-based simulation: Vibration correlates to Temp
            base_vibration = np.random.uniform(2.0, 4.0)
            # Add a random "Failure Spike" (Anomalous data)
            if np.random.rand() > 0.95: 
                base_vibration *= 3 
            
            temp = 25 + (base_vibration * 5) + np.random.normal(0, 2)
            
            records.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'machine_id': m,
                'vibration_rms': round(base_vibration, 4),
                'temp_c': round(temp, 2),
                'power_kw': round(np.random.uniform(10.0, 15.0), 2)
            })
        return pd.DataFrame(records)

    def run(self):
        print("🚀 Ingestion started. Press Ctrl+C to stop.")
        while True:
            df = self.generate_batch()
            # Bronze Layer: Always Append (Never Overwrite)
            df.to_csv(self.data_path, mode='a', header=not os.path.exists(self.data_path), index=False)
            time.sleep(3)

if __name__ == "__main__":
    sim = SmartFactorySimulator()
    sim.run()
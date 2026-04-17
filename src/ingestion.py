import pandas as pd
import numpy as np
import time
import os
from datetime import datetime

class SmartFactorySimulator:
    def __init__(self):
        self.machines = [
            # Turbines
            'TURBINE_01', 'TURBINE_02', 'TURBINE_03',
            # Pumps
            'PUMP_01', 'PUMP_02', 'PUMP_03', 'PUMP_04',
            # Compressors
            'COMPRESSOR_01', 'COMPRESSOR_02', 'COMPRESSOR_03',
            # Heat Exchangers
            'HEAT_EXCHANGER_01', 'HEAT_EXCHANGER_02',
            # Motors
            'MOTOR_01', 'MOTOR_02', 'MOTOR_03',
            # Generators
            'GENERATOR_01', 'GENERATOR_02'
        ]

        # Each machine type has different normal operating ranges
        self.machine_profiles = {
            'TURBINE':        {'vibration': (2.0, 4.0), 'temp': (60, 80),  'power': (45, 60)},
            'PUMP':           {'vibration': (1.0, 3.0), 'temp': (35, 55),  'power': (10, 20)},
            'COMPRESSOR':     {'vibration': (3.0, 5.0), 'temp': (70, 90),  'power': (30, 45)},
            'HEAT_EXCHANGER': {'vibration': (0.5, 1.5), 'temp': (90, 120), 'power': (5,  10)},
            'MOTOR':          {'vibration': (1.5, 3.5), 'temp': (45, 65),  'power': (20, 35)},
            'GENERATOR':      {'vibration': (2.5, 4.5), 'temp': (55, 75),  'power': (80, 120)},
        }

        self.data_path = 'data/bronze_sensors.csv'
        if not os.path.exists('data'):
            os.makedirs('data')

    def get_profile(self, machine_id):
        for key in self.machine_profiles:
            if key in machine_id:
                return self.machine_profiles[key]
        return self.machine_profiles['MOTOR']

    def generate_batch(self):
        records = []
        for machine_id in self.machines:
            profile = self.get_profile(machine_id)

            base_vibration = np.random.uniform(*profile['vibration'])

            # 5% chance of failure spike
            failure_spike = np.random.rand() > 0.95
            if failure_spike:
                base_vibration *= np.random.uniform(2.5, 4.0)

            # 3% chance of gradual degradation (vibration slowly increasing)
            degradation = np.random.rand() > 0.97
            if degradation:
                base_vibration *= np.random.uniform(1.5, 2.0)

            temp = profile['temp'][0] + (base_vibration * 3) + np.random.normal(0, 3)

            # Power spikes during high vibration
            power_multiplier = 1.3 if failure_spike else 1.0
            power = np.random.uniform(*profile['power']) * power_multiplier

            records.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'machine_id': machine_id,
                'machine_type': machine_id.split('_')[0] + '_' + machine_id.split('_')[1] if 'EXCHANGER' not in machine_id else 'HEAT_EXCHANGER',
                'vibration_rms': round(base_vibration, 4),
                'temp_c': round(temp, 2),
                'power_kw': round(power, 2),
                'failure_spike': failure_spike,
                'degradation': degradation
            })
        return pd.DataFrame(records)

    def run(self):
        print(f"🚀 Ingestion started. Monitoring {len(self.machines)} machines.")
        while True:
            df = self.generate_batch()
            file_exists = os.path.exists(self.data_path)
            df.to_csv(self.data_path, mode='a', header=not file_exists, index=False)
            print(f"✅ Batch written — {len(df)} records at {datetime.now().strftime('%H:%M:%S')}")
            time.sleep(3)

if __name__ == "__main__":
    sim = SmartFactorySimulator()
    sim.run()
"""
Wear-based sensor simulator for the Industrial Agentic AI System.

Each machine has a HIDDEN wear level (0 = new, 1 = failure). Wear grows as a
random process. Sensors react to wear, but wear itself is never written to the
output that goes to Snowflake. A second file keeps the true wear for checking.

Run:  python wear_simulator.py
Out:  data/backfill_sensors.csv   (same columns as bronze_sensors.csv)
      data/backfill_truth.csv     (hidden wear, for plots and checks only)
"""
import os
import numpy as np
import pandas as pd

SEED = 42
DAYS = 30
STEP_MIN = 10
STEPS_PER_DAY = 24 * 60 // STEP_MIN          # 144
DOWNTIME_STEPS = 36                          # 6 hours of repair, no readings
CYCLE_SCALE = 1.9                            # stretches cycles to the target length

MACHINES = [
    'TURBINE_01', 'TURBINE_02', 'TURBINE_03',
    'PUMP_01', 'PUMP_02', 'PUMP_03', 'PUMP_04',
    'COMPRESSOR_01', 'COMPRESSOR_02', 'COMPRESSOR_03',
    'HEAT_EXCHANGER_01', 'HEAT_EXCHANGER_02',
    'MOTOR_01', 'MOTOR_02', 'MOTOR_03',
    'GENERATOR_01', 'GENERATOR_02',
]

# Same normal ranges as ingestion.py
PROFILES = {
    'TURBINE':        {'vibration': (2.0, 4.0), 'temp': (60, 80),  'power': (45, 60)},
    'PUMP':           {'vibration': (1.0, 3.0), 'temp': (35, 55),  'power': (10, 20)},
    'COMPRESSOR':     {'vibration': (3.0, 5.0), 'temp': (70, 90),  'power': (30, 45)},
    'HEAT_EXCHANGER': {'vibration': (0.5, 1.5), 'temp': (90, 120), 'power': (5, 10)},
    'MOTOR':          {'vibration': (1.5, 3.5), 'temp': (45, 65),  'power': (20, 35)},
    'GENERATOR':      {'vibration': (2.5, 4.5), 'temp': (55, 75),  'power': (80, 120)},
}

# Typical days from new to failure per type (before the random factors below)
CYCLE_DAYS = {
    'TURBINE': 11, 'PUMP': 8, 'COMPRESSOR': 7,
    'HEAT_EXCHANGER': 12, 'MOTOR': 9, 'GENERATOR': 10,
}


def type_of(machine_id):
    for key in PROFILES:
        if key in machine_id:
            return key
    return 'MOTOR'


def simulate_machine(machine_id, end_time, rng):
    mtype = type_of(machine_id)
    prof = PROFILES[mtype]

    # Machine character: fixed for the whole month
    base_vib = rng.uniform(*prof['vibration'])
    base_temp = rng.uniform(*prof['temp'])
    base_power = rng.uniform(*prof['power'])
    speed = rng.lognormal(0.0, 0.15)                 # some machines are just worse
    mean_step = 1.0 / (CYCLE_DAYS[mtype] * CYCLE_SCALE * STEPS_PER_DAY) * speed

    n_steps = DAYS * STEPS_PER_DAY
    t0 = end_time - pd.Timedelta(minutes=STEP_MIN * n_steps)

    wear = rng.uniform(0.0, 0.5)                     # machines start at different ages
    log_rate = 0.0                                   # slowly wandering wear speed
    down_left = 0
    rows, truth = [], []

    for i in range(n_steps):
        ts = t0 + pd.Timedelta(minutes=STEP_MIN * i)

        if down_left > 0:                            # machine is being repaired
            down_left -= 1
            continue

        # 1. wear speed wanders (mean-reverting random walk on the log scale)
        log_rate += -0.01 * log_rate + rng.normal(0, 0.06)
        hour = ts.hour + ts.minute / 60
        load = 1.0 + 0.3 * np.sin((hour - 6) / 24 * 2 * np.pi)   # busier by day
        late = 1.0 + 1.0 * max(0.0, wear - 0.6)                  # worn parts wear faster

        # 2. random wear increment (gamma: always positive, noisy)
        mean_inc = mean_step * np.exp(log_rate) * load * late
        inc = rng.gamma(shape=0.5, scale=mean_inc / 0.5)

        # 3. rare shock (load surge, bad start-up)
        if rng.random() < 0.002:
            inc += rng.uniform(0.01, 0.04)
        wear = min(wear + inc, 1.0)

        # 4. sensors react to wear, with noise (wear itself is not recorded)
        vib = base_vib * (1 + 1.2 * wear ** 2) + rng.normal(0, 0.06 * base_vib)
        temp = base_temp + 15 * wear ** 1.5 + rng.normal(0, 1.5)
        power = base_power * (1 + 0.15 * wear) * (1 + 0.05 * (load - 1)) \
            * (1 + rng.normal(0, 0.03))
        degradation = bool(vib > 1.5 * base_vib)

        # 5. failure: chance rises steeply with wear, forced at wear = 1
        hazard = 0.0001 + 0.06 * wear ** 8
        failed = bool(wear >= 1.0 or rng.random() < hazard)
        if failed:
            vib *= rng.uniform(2.0, 3.0)
            power *= 1.3

        rows.append({
            'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S'),
            'machine_id': machine_id,
            # same convention as ingestion.py (type column mirrors the id)
            'machine_type': 'HEAT_EXCHANGER' if 'EXCHANGER' in machine_id else machine_id,
            'vibration_rms': round(vib, 4),
            'temp_c': round(temp, 2),
            'power_kw': round(power, 2),
            'failure_spike': failed,
            'degradation': degradation,
        })
        truth.append({'timestamp': ts, 'machine_id': machine_id,
                      'wear': wear, 'failed': failed})

        if failed:                                   # repair, wear resets
            wear = rng.uniform(0.0, 0.05)
            log_rate = 0.0
            down_left = DOWNTIME_STEPS

    return rows, truth


def main():
    rng = np.random.default_rng(SEED)
    end_time = pd.Timestamp.now().floor(f'{STEP_MIN}min')
    all_rows, all_truth = [], []
    for m in MACHINES:
        r, t = simulate_machine(m, end_time, rng)
        all_rows += r
        all_truth += t

    os.makedirs('data', exist_ok=True)
    sensors = pd.DataFrame(all_rows).sort_values(['timestamp', 'machine_id'])
    truth = pd.DataFrame(all_truth).sort_values(['timestamp', 'machine_id'])
    sensors.to_csv('data/backfill_sensors.csv', index=False)
    truth.to_csv('data/backfill_truth.csv', index=False)

    fails = truth[truth.failed].groupby('machine_id').size()
    print(f"rows: {len(sensors)}   machines: {sensors.machine_id.nunique()}")
    print(f"failures per machine: min {fails.min()}  median {int(fails.median())}  max {fails.max()}"
          f"   (machines with none: {len(MACHINES) - len(fails)})")


if __name__ == '__main__':
    main()

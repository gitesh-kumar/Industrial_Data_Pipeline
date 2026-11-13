"""
Wear-based sensor simulator for the Industrial Agentic AI System.

Each machine has a HIDDEN wear level (0 = new, 1 = failure). Wear grows as a
random process. Sensors react to wear, but wear itself is never written to the
output that goes to Snowflake. A second file keeps the true wear for checking.

How the month ends is set on purpose (END_WEAR_BANDS below): a few machines
finish close to failure, some in the middle, most healthy. How each machine gets
there is simulated. The model never sees these targets, only the sensors.

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


# Scenario: how worn each machine should be at the END of the 30 days (0 to 1).
# Machines not listed get DEFAULT_BAND. These numbers are my own choice for the
# demo, not measured values. The README must say so.
END_WEAR_BANDS = {
    'COMPRESSOR_02': (0.80, 0.95), 'PUMP_03': (0.80, 0.95),                  # close to failure
    'HEAT_EXCHANGER_01': (0.58, 0.68), 'MOTOR_02': (0.58, 0.68),
    'TURBINE_01': (0.58, 0.68),                                              # getting worse
    'PUMP_01': (0.42, 0.52), 'GENERATOR_02': (0.42, 0.52),
    'COMPRESSOR_03': (0.42, 0.52),                                           # keep an eye on
}
DEFAULT_BAND = (0.02, 0.35)                                                  # healthy
MAX_TRIES = 600


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
            'machine_type': machine_id.rsplit('_', 1)[0],
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


def end_state(rows, truth, last_ts):
    """Wear at the last step, or None if the machine was in repair at the end."""
    if not rows or rows[-1]['timestamp'] != last_ts.strftime('%Y-%m-%d %H:%M:%S'):
        return None
    return 0.0 if truth[-1]['failed'] else truth[-1]['wear']


def simulate_to_target(idx, machine_id, end_time):
    """Run the machine with fresh random numbers until it ends the month inside its band."""
    lo, hi = END_WEAR_BANDS.get(machine_id, DEFAULT_BAND)
    last_ts = end_time - pd.Timedelta(minutes=STEP_MIN)
    best, best_gap = None, 9.0
    for attempt in range(MAX_TRIES):
        rng = np.random.default_rng([SEED, idx, attempt])          # same result every run
        rows, truth = simulate_machine(machine_id, end_time, rng)
        w = end_state(rows, truth, last_ts)
        if w is None:
            continue
        if lo <= w <= hi:
            return rows, truth, w, attempt + 1
        gap = min(abs(w - lo), abs(w - hi))
        if gap < best_gap:
            best, best_gap = (rows, truth, w), gap
    rows, truth, w = best                                           # closest we found
    return rows, truth, w, MAX_TRIES


def main():
    end_time = pd.Timestamp.now().floor(f'{STEP_MIN}min')
    all_rows, all_truth = [], []
    print("machine              wear at end   tries")
    for i, m in enumerate(MACHINES):
        r, t, w, tries = simulate_to_target(i, m, end_time)
        all_rows += r
        all_truth += t
        print(f"{m:<20} {w:>10.2f} {tries:>7}")

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

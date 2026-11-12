"""
What the assistant is told about the database.

The model never sees the data. It sees this text: which tables exist, what
each column means, which values a column can hold, and a few worked
examples. Most wrong answers come from a model guessing at one of those
things (a column name, a literal like 'Yes', what "efficient" means).

Run it on its own to check the text against the real database:

    python data_dictionary.py

It fails if a documented column is missing, if an example query errors, or
if a documented value does not exist in the data.
"""
import sqlite3
import sys

DB_PATH = "factory_lakehouse.db"

# ── TABLES ──────────────────────────────────────────────────────────────
# (name, type, meaning)
TABLES = {
    "gold_operations_status": {
        "about": (
            "One row per machine (17 rows). Summary of the newest 24 hours "
            "of readings, counted back from as_of. Use this table for almost "
            "every question about machines, risk, cost, temperature, status "
            "and recommendations. 'Now' and 'current' mean this table."
        ),
        "columns": [
            ("machine_id", "TEXT", "Unique machine, for example 'PUMP_03' or 'HEAT_EXCHANGER_01'."),
            ("machine_type", "TEXT", "Machine type: one of the six values listed under VALUES."),
            ("total_readings", "INTEGER", "Number of sensor readings in the window."),
            ("avg_power_usage", "REAL", "Average power draw in kW."),
            ("peak_power_kw", "REAL", "Highest power draw in kW."),
            ("avg_temp", "REAL", "Average temperature in degrees Celsius."),
            ("max_temp", "REAL", "Highest temperature in degrees Celsius."),
            ("avg_vibration", "REAL", "Average vibration RMS (no unit is recorded)."),
            ("max_vibration", "REAL", "Highest vibration RMS."),
            ("avg_risk_score", "REAL", "Average risk score, 0 to 100."),
            ("max_risk_score", "REAL", "Highest risk score, 0 to 100."),
            ("failure_spike_count", "INTEGER", "Readings flagged FAILURE_SPIKE in the window."),
            ("degradation_count", "INTEGER", "Readings flagged DEGRADATION_WARN in the window."),
            ("hourly_energy_cost_eur", "REAL", "Energy cost in EUR per hour: average power in MW times the simulated price."),
            ("efficiency_status", "TEXT", "Temperature status against the machine type's own limits."),
            ("recommendation", "TEXT", "Rule-based action for the machine."),
            ("energy_price_eur_mwh", "REAL", "Simulated energy price in EUR per MWh used for the cost."),
            ("temp_warn_c", "REAL", "Temperature above which the status becomes WARNING for this machine's type."),
            ("temp_crit_c", "REAL", "Temperature above which the status becomes CRITICAL for this machine's type."),
            ("window_hours", "INTEGER", "Length of the window, in hours."),
            ("as_of", "TEXT", "End of the window: time of the newest reading."),
        ],
    },
    "silver_telemetry": {
        "about": (
            "One row per sensor reading, cleaned. Use it only for questions "
            "about single readings, counts of flagged readings, or change "
            "over time. For a per-machine summary use gold_operations_status."
        ),
        "columns": [
            ("timestamp", "TEXT", "Reading time as 'YYYY-MM-DD HH:MM:SS' (sorts correctly as text)."),
            ("machine_id", "TEXT", "Same ids as in gold_operations_status."),
            ("machine_type", "TEXT", "Same six types."),
            ("vibration_rms", "REAL", "Vibration RMS of this reading."),
            ("temp_c", "REAL", "Temperature in degrees Celsius."),
            ("power_kw", "REAL", "Power draw in kW."),
            ("failure_spike", "INTEGER", "1 if the sensor simulator produced a failure spike, else 0."),
            ("degradation", "INTEGER", "1 if the simulator produced a degradation reading, else 0."),
            ("quality_flag", "TEXT", "One flag per reading, see VALUES."),
            ("temp_f", "REAL", "Temperature in Fahrenheit."),
            ("risk_score", "REAL", "Risk score of this reading, 0 to 100."),
        ],
    },
}

# ── VALUES ──────────────────────────────────────────────────────────────
# Allowed values per column. Without this the model writes things like
# recommendation = 'Maintenance' and gets zero rows.
VALUES = {
    "machine_type": ["COMPRESSOR", "GENERATOR", "HEAT_EXCHANGER", "MOTOR", "PUMP", "TURBINE"],
    "efficiency_status": ["OPTIMAL", "WARNING", "CRITICAL"],
    "recommendation": ["CONTINUE", "REDUCE_LOAD", "SCHEDULE_MAINTENANCE", "IMMEDIATE_SHUTDOWN"],
    "quality_flag": ["PASS", "FAILURE_SPIKE", "DEGRADATION_WARN", "VIBRATION_CRITICAL", "HIGH_TEMP_WARN"],
}

# ── RULES ───────────────────────────────────────────────────────────────
# Meanings and word choices a person would assume without saying so.
RULES = [
    "All data is simulated. Never describe it as real plant data.",
    "Machine types are stored in the singular and in capitals: 'generators' means machine_type = 'GENERATOR'.",
    "'Power', 'power consumption' and 'energy used' mean avg_power_usage (kW). 'Cost' and 'energy cost' mean hourly_energy_cost_eur (EUR per hour).",
    "'Total ... of all X' means SUM over the machines of type X. 'Per machine' or 'average' means AVG.",
    "'Which machine type uses the most energy' means the total: SUM(avg_power_usage) grouped by machine_type.",
    "'Failure spikes' means failure_spike_count. 'Degradation' means degradation_count.",
    "'Warning status' and 'critical status' mean efficiency_status. It is a temperature status. No efficiency ratio exists in the data.",
    "'Most efficient machine by energy' has no column of its own. Use the lowest avg_power_usage and say that machine types have different normal power levels.",
    "'Needs maintenance' or 'needs attention' means recommendation <> 'CONTINUE'.",
    "Risk score is relative: 60 percent vibration and 40 percent temperature, each divided by the highest value in the data. It is not a probability of failure.",
    "The data has no history of past months. Do not answer questions about trends over weeks or months, or about the future.",
]

# ── WORKED EXAMPLES ─────────────────────────────────────────────────────
# (question, SQL). Kept different from the evaluation questions on purpose,
# so the evaluation measures understanding and not memory.
EXAMPLES = [
    ("Which machine has the lowest risk score?",
     "SELECT machine_id, machine_type, avg_risk_score FROM gold_operations_status "
     "ORDER BY avg_risk_score ASC LIMIT 1"),
    ("What is the combined hourly energy cost of all pumps?",
     "SELECT ROUND(SUM(hourly_energy_cost_eur), 4) AS total_cost_eur_per_hour "
     "FROM gold_operations_status WHERE machine_type = 'PUMP'"),
    ("Which machine type has the highest total power draw?",
     "SELECT machine_type, ROUND(SUM(avg_power_usage), 2) AS total_power_kw "
     "FROM gold_operations_status GROUP BY machine_type ORDER BY total_power_kw DESC LIMIT 1"),
    ("What is the average vibration for each machine type?",
     "SELECT machine_type, ROUND(AVG(avg_vibration), 2) AS avg_vibration, COUNT(*) AS machines "
     "FROM gold_operations_status GROUP BY machine_type ORDER BY avg_vibration DESC"),
    ("Which machines should be shut down?",
     "SELECT machine_id, machine_type, avg_temp, temp_crit_c FROM gold_operations_status "
     "WHERE recommendation = 'IMMEDIATE_SHUTDOWN'"),
    ("How many failure-spike readings does each machine type have?",
     "SELECT machine_type, COUNT(*) AS spike_readings FROM silver_telemetry "
     "WHERE quality_flag = 'FAILURE_SPIKE' GROUP BY machine_type ORDER BY spike_readings DESC"),
    ("What was the last temperature reading of MOTOR_02?",
     "SELECT timestamp, temp_c FROM silver_telemetry WHERE machine_id = 'MOTOR_02' "
     "ORDER BY timestamp DESC LIMIT 1"),
    ("Which conveyor belt has the highest load?",
     "CANNOT_ANSWER: the data has no conveyor belts. It covers compressors, generators, "
     "heat exchangers, motors, pumps and turbines."),
]


def render_context() -> str:
    """The text that goes into the prompt."""
    out = ["DATABASE (SQLite). Read-only. These are the only tables you may use.", ""]
    for name, t in TABLES.items():
        out.append(f"TABLE {name}")
        out.append(f"  {t['about']}")
        for col, typ, desc in t["columns"]:
            out.append(f"  - {col} ({typ}): {desc}")
        out.append("")
    out.append("VALUES (use these exact spellings in WHERE clauses):")
    for col, vals in VALUES.items():
        out.append(f"  - {col}: " + ", ".join(f"'{v}'" for v in vals))
    out.append("")
    out.append("RULES:")
    for r in RULES:
        out.append(f"  - {r}")
    out.append("")
    out.append("EXAMPLES:")
    for q, sql in EXAMPLES:
        out.append(f"Question: {q}")
        out.append(f"Answer: {sql}")
        out.append("")
    return "\n".join(out)


def allowed_tables() -> set:
    return set(TABLES)


# ── CHECK AGAINST THE REAL DATABASE ─────────────────────────────────────
def check(db_path: str = DB_PATH) -> bool:
    ok = True
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    for table, t in TABLES.items():
        real = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        doc = [c[0] for c in t["columns"]]
        missing = [c for c in doc if c not in real]
        undocumented = [c for c in real if c not in doc]
        if missing:
            ok = False
            print(f"FAIL {table}: documented but not in the database: {missing}")
        if undocumented:
            ok = False
            print(f"FAIL {table}: in the database but not documented: {undocumented}")
        if not missing and not undocumented:
            print(f"ok   {table}: {len(doc)} columns match")

    for col, vals in VALUES.items():
        found = set()
        for table in TABLES:
            if col in [c[0] for c in TABLES[table]["columns"]]:
                found |= {r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM {table}")}
        unknown = found - set(vals)
        if unknown:
            ok = False
            print(f"FAIL {col}: values in the data that are not documented: {sorted(unknown)}")
        else:
            print(f"ok   {col}: every value in the data is documented "
                  f"({len(found)} of {len(vals)} present)")

    for q, sql in EXAMPLES:
        if sql.startswith("CANNOT_ANSWER"):
            continue
        try:
            n = len(conn.execute(sql).fetchall())
            print(f"ok   example runs ({n} rows): {q}")
        except Exception as e:
            ok = False
            print(f"FAIL example: {q}\n     {e}")
    conn.close()
    return ok


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    sys.exit(0 if check(path) else 1)

# Snowflake track

This folder rebuilds the Snowflake side of the project from scratch. It runs next to the SQLite pipeline and is not used by the Railway demo, so the demo keeps working when the Snowflake trial ends.

Run the SQL in Snowsight or in the Snowflake extension for VS Code. Run all commands from the project root.

## Order

| Step | Role to use | What it does |
|---|---|---|
| `00_setup.sql` | ACCOUNTADMIN, then ENGINEER | Roles, warehouse, database, schemas, grants, loader service user |
| `01_bronze.sql` | INDUSTRIAL_INGEST | Raw tables for sensor readings and the energy price |
| `python src/wear_simulator.py` | | Writes 30 days of simulated history to `data/backfill_sensors.csv` |
| `python load_backfill.py` | | Loads the history into Bronze |
| `02_silver.sql` | INDUSTRIAL_TRANSFORM | Cleaned data with quality flags and risk score, as a dynamic table |
| `03_quality_checks.sql` | ENGINEER, then TRANSFORM | Eight data quality checks on Silver, hourly |
| `04_gold_rules.sql` | INDUSTRIAL_TRANSFORM | Rule-based Gold: cost and recommendation per machine |
| `05_features.sql` | INDUSTRIAL_TRANSFORM | Rolling features and the days-until-failure label |
| `python train_rul.py` | | Trains the model and compares it with the rules |
| `python score_rul.py` | | Writes predictions into Gold |
| `06_predictions.sql` | ENGINEER, then TRANSFORM | Predictions table and Gold table with maintenance priority |

In Snowsight, pick the role in the dropdown at the top right. A `USE ROLE` line inside a worksheet did not switch the role reliably there. Snowsight also runs only the selected statement, so press Ctrl+A before running a whole file. After switching roles, check with `SELECT CURRENT_ROLE();`.

## Roles

| Role | Can |
|---|---|
| INDUSTRIAL_ENGINEER | Own the database, create the check functions, hand out grants |
| INDUSTRIAL_INGEST | Create and fill tables in BRONZE |
| INDUSTRIAL_TRANSFORM | Read BRONZE, own the SILVER and GOLD dynamic tables |
| INDUSTRIAL_READER | Read SILVER and GOLD only |
| INDUSTRIAL_ML | Read the features table, write the predictions table |

Roles limit what a mistake or a leaked credential can touch. They do not make the data correct. If Bronze is wrong, everything built on it is wrong.

## Login for the Python scripts

The scripts log in as the service user `INDUSTRIAL_LOADER` with a key pair, no password. Generate the keys outside the repository:

```bash
mkdir -p ~/.snowflake
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/rsa.p8 -nocrypt
openssl rsa -in ~/.snowflake/rsa.p8 -pubout -out ~/.snowflake/rsa.pub
```

The public key goes into `00_setup.sql` (without the BEGIN and END lines). The private key `rsa.p8` stays on your machine and is never committed or pasted anywhere. The scripts read these values from `.env`:

```
SNOWFLAKE_ACCOUNT=<orgname>-<accountname>
SNOWFLAKE_USER=INDUSTRIAL_LOADER
SNOWFLAKE_PRIVATE_KEY_FILE=C:/Users/<you>/.snowflake/rsa.p8
```

Use forward slashes and no quotes around the path. A quoted Windows path with backslashes breaks in `.env`.

## Things worth knowing

- Everything here is a batch pipeline. The dynamic tables refresh with a one hour target lag, and `score_rul.py` runs when you run it. Nothing is live.
- The history is simulated: 17 machines, 30 days, 10-minute readings, hidden wear per machine. See the main README for what that means for the results.
- Recreating `SILVER_TELEMETRY` removes the data quality checks attached to it and invalidates the Gold tables built on it. Run `03`, `04`, `05` and `06` again afterwards.
- `00_setup.sql` was rebuilt from the worksheet sessions and has not been run from an empty account. The function bodies in `03_quality_checks.sql` come from the deployed functions. The other files are the SQL that ran.
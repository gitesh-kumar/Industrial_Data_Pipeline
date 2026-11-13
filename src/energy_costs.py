"""
Energy cost of the machines, priced with the real hourly day-ahead price.

Only machines that CONSUME electricity are counted. Turbines and generators
produce power, so their power_kw is not a cost.

How a cost is calculated
  1. average power of a machine in one hour (kW)  =  energy of that hour (kWh)
  2. cost of that hour  =  kWh x price (EUR/MWh) / 1000

The sensor data is simulated, so its dates do not have to match the real price
dates. Readings are matched to the real prices by the same hour of the day and
the same weekday, using the nearest whole number of weeks. If the readings lie
inside the price range already (live data), nothing is shifted.
"""
import pandas as pd
from sqlalchemy import create_engine, text

CONSUMER_TYPES = ("PUMP", "COMPRESSOR", "MOTOR", "HEAT_EXCHANGER")
HOURS_DAY = 24
HOURS_MONTH = 30 * 24


def _engine(engine):
    return engine or create_engine("sqlite:///factory_lakehouse.db")


def has_prices(engine=None) -> bool:
    with _engine(engine).connect() as c:
        r = c.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='energy_prices'")).fetchone()
        if not r:
            return False
        return c.execute(text("SELECT COUNT(*) FROM energy_prices")).scalar() > 0


def load_prices(engine=None) -> pd.Series:
    df = pd.read_sql("SELECT hour, price_eur_mwh FROM energy_prices", _engine(engine))
    df["hour"] = pd.to_datetime(df["hour"])
    return df.drop_duplicates("hour").set_index("hour")["price_eur_mwh"].sort_index()


def week_shift(first, last, prices: pd.Series) -> pd.Timedelta:
    """Whole weeks to add to the readings so that they fall inside the price range."""
    if first >= prices.index.min() and last <= prices.index.max():
        return pd.Timedelta(0)
    gap_days = (prices.index.max().normalize() - last.normalize()).days
    return pd.Timedelta(days=(gap_days // 7) * 7)


def latest_price(engine=None):
    """Price of the hour of the newest reading, or None when no prices are loaded."""
    eng = _engine(engine)
    if not has_prices(eng):
        return None
    with eng.connect() as c:
        row = c.execute(text("SELECT MIN(timestamp), MAX(timestamp) FROM silver_telemetry")).fetchone()
    if not row or row[1] is None:
        return None
    prices = load_prices(eng)
    shift = week_shift(pd.Timestamp(row[0]), pd.Timestamp(row[1]), prices)
    h = (pd.Timestamp(row[1]) + shift).floor("h")
    return float(prices.get(h, prices.iloc[-1]))


def compute_energy(engine=None) -> dict:
    eng = _engine(engine)
    if not has_prices(eng):
        raise LookupError("No electricity prices loaded. Run load_prices.py first.")
    prices = load_prices(eng)

    marks = ",".join(f"'{t}'" for t in CONSUMER_TYPES)
    df = pd.read_sql(
        f"""SELECT machine_id, strftime('%Y-%m-%d %H:00:00', timestamp) AS hour, AVG(power_kw) AS kwh
            FROM silver_telemetry WHERE machine_type IN ({marks}) GROUP BY machine_id, hour""", eng)
    if df.empty:
        raise LookupError("No readings of energy-consuming machines.")
    df["hour"] = pd.to_datetime(df["hour"])

    last = df["hour"].max()
    shift = week_shift(df["hour"].min(), last, prices)
    df["price"] = (df["hour"] + shift).map(prices)
    priced = df.dropna(subset=["price"]).copy()
    priced["cost"] = priced["kwh"] * priced["price"] / 1000.0

    day = priced[priced["hour"] > last - pd.Timedelta(hours=HOURS_DAY)]
    month = priced[priced["hour"] > last - pd.Timedelta(hours=HOURS_MONTH)]

    hours = []
    by_hour = day.groupby("hour")["cost"].sum()
    for h in pd.date_range(end=last, periods=HOURS_DAY, freq="h"):
        hours.append({"label": h.strftime("%H:00"),
                      "price_eur_mwh": None if (h + shift) not in prices.index else round(float(prices[h + shift]), 2),
                      "cost_eur": round(float(by_hour.get(h, 0.0)), 2)})
    # a missing price leaves a gap in the chart, shown as 0
    for x in hours:
        if x["price_eur_mwh"] is None:
            x["price_eur_mwh"] = 0.0

    per_machine = (month.groupby("machine_id")["cost"].sum().round(2).sort_values(ascending=False))
    return {
        "cost_24h_eur": round(float(day["cost"].sum()), 2),
        "cost_30d_eur": round(float(month["cost"].sum()), 2),
        "hours": hours,
        "machines": [{"machine_id": m, "cost_30d_eur": float(v)} for m, v in per_machine.items()],
        "hours_covered": int(month["hour"].nunique()),
        "hours_without_price": int(len(df) - len(priced)),
        "as_of": last.strftime("%Y-%m-%d %H:%M:%S"),
        "price_source": "Day-ahead price DE-LU, Bundesnetzagentur | SMARD.de, CC BY 4.0",
        "counted_types": list(CONSUMER_TYPES),
        "readings_shifted_days": int(shift.days),
    }

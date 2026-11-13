"""
Downloads real German day-ahead electricity prices and stores them as hourly
prices, so the dashboard can price the energy the machines use.

Source: Energy-Charts API (Fraunhofer ISE), bidding zone DE-LU.
        Data: Bundesnetzagentur | SMARD.de, licence CC BY 4.0.
Since 1 Oct 2025 the day-ahead market trades in 15-minute steps. We average
the steps of each hour, so the table always has one price per hour.

Run it on your PC, with internet:

    python load_prices.py

It writes data/day_ahead_prices.csv (commit this file, the Railway demo reads
it) and, if factory_lakehouse.db exists, the table energy_prices in it.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

import pandas as pd

API = "https://api.energy-charts.info/price"
ZONE = "DE-LU"
TIMEZONE = "Europe/Berlin"


def fetch(start: date, end: date) -> dict:
    url = API + "?" + urllib.parse.urlencode(
        {"bzn": ZONE, "start": start.isoformat(), "end": end.isoformat()})
    req = urllib.request.Request(url, headers={"User-Agent": "industrial-data-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def to_hourly(unix_seconds, prices) -> pd.DataFrame:
    """15-minute (or hourly) prices -> one price per local hour (mean of the steps).
    Missing values are skipped. Hours are Berlin time, written as plain text."""
    df = pd.DataFrame({"ts": unix_seconds, "p": prices}).dropna()
    local = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TIMEZONE)
    # Plain local clock time. The one hour that repeats when the clocks go back
    # appears once, as the mean of both.
    df["hour"] = local.dt.tz_localize(None).dt.floor("h")
    out = df.groupby("hour", as_index=False)["p"].mean().rename(columns={"p": "price_eur_mwh"})
    out["price_eur_mwh"] = out["price_eur_mwh"].round(2)
    out["hour"] = out["hour"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=35, help="how many days back to load")
    ap.add_argument("--csv", default="data/day_ahead_prices.csv")
    ap.add_argument("--db", default="factory_lakehouse.db")
    args = ap.parse_args()

    end = date.today() + timedelta(days=1)       # tomorrow's prices exist from about 13:00
    start = date.today() - timedelta(days=args.days)
    try:
        raw = fetch(start, end)
    except Exception as e:
        sys.exit(f"Could not download the prices: {e}\nCheck your internet connection and run it again.")
    if "unix_seconds" not in raw or "price" not in raw:
        sys.exit(f"Unexpected answer from the price API. Keys: {list(raw)[:8]}")

    hourly = to_hourly(raw["unix_seconds"], raw["price"])
    if hourly.empty:
        sys.exit("The price API returned no prices for this period.")

    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    hourly.to_csv(args.csv, index=False)
    p = hourly["price_eur_mwh"]
    print(f"{len(hourly)} hourly prices, {hourly['hour'].iloc[0]} to {hourly['hour'].iloc[-1]}")
    print(f"min {p.min():.1f}  mean {p.mean():.1f}  max {p.max():.1f} EUR/MWh   hours below zero: {(p < 0).sum()}")
    print(f"written: {args.csv}")

    if os.path.exists(args.db):
        from sqlalchemy import create_engine
        hourly.to_sql("energy_prices", create_engine(f"sqlite:///{args.db}"), if_exists="replace", index=False)
        print(f"table energy_prices written to {args.db}")
    else:
        print(f"{args.db} not found, so no table was written. Run the pipeline or build_demo_db.py, "
              "then run this script again.")
    print("Prices: Bundesnetzagentur | SMARD.de, CC BY 4.0, via api.energy-charts.info")


if __name__ == "__main__":
    main()

import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from energy_api import EnergyMarketAPI

engine = create_engine('sqlite:///factory_lakehouse.db')

# Gold looks at the newest WINDOW_HOURS of data, counted back from the
# newest reading (not from today, so old data still produces a result).
WINDOW_HOURS = 24

# Highest temperature a healthy machine of each type reaches. These are the
# upper ends of the temperature profiles in ingestion.py.
NORMAL_MAX_TEMP_C = {
    'TURBINE': 80, 'PUMP': 55, 'COMPRESSOR': 90,
    'HEAT_EXCHANGER': 120, 'MOTOR': 65, 'GENERATOR': 75,
}
DEFAULT_NORMAL_MAX_C = 80      # for a type that is not in the table above

# Rule limits. In the simulator wear raises the temperature by 15 C at most, so
# the limits sit close above the normal maximum. A real plant would use wider
# margins (for example 10 C and 25 C). These values are tuned to the simulated
# data and must be described that way in the README.
WARN_MARGIN_C = 1.5            # average temperature this far above the type maximum: WARNING
CRIT_MARGIN_C = 3.5            # this far above: CRITICAL
SPIKES_FOR_MAINTENANCE = 1     # failure spikes in the window that trigger SCHEDULE_MAINTENANCE
HIGH_PRICE_EUR_MWH = 120       # price above which a WARNING machine should reduce load

def generate_financial_gold():
    # Real day-ahead price when prices are loaded (load_prices.py),
    # otherwise the simulated price from energy_api.py.
    current_price_eur = None
    try:
        from energy_costs import latest_price
        current_price_eur = latest_price(engine)
    except Exception:
        current_price_eur = None
    if current_price_eur is None:
        current_price_eur = EnergyMarketAPI().get_current_price()['price']

    print(f"⚡ Current Energy Price: {current_price_eur} EUR/MWh")

    latest = pd.read_sql(
        "SELECT MAX(timestamp) AS t FROM silver_telemetry", engine
    )['t'].iloc[0]

    query = f"""
    SELECT 
        machine_id,
        machine_type,
        COUNT(*) as total_readings,
        AVG(power_kw) as avg_power_usage,
        MAX(power_kw) as peak_power_kw,
        AVG(temp_c) as avg_temp,
        MAX(temp_c) as max_temp,
        AVG(vibration_rms) as avg_vibration,
        MAX(vibration_rms) as max_vibration,
        AVG(risk_score) as avg_risk_score,
        MAX(risk_score) as max_risk_score,
        SUM(CASE WHEN quality_flag = 'FAILURE_SPIKE' THEN 1 ELSE 0 END) as failure_spike_count,
        SUM(CASE WHEN quality_flag = 'DEGRADATION_WARN' THEN 1 ELSE 0 END) as degradation_count,
        ROUND((AVG(power_kw) / 1000) * {current_price_eur}, 4) as hourly_energy_cost_eur
    FROM silver_telemetry
    WHERE timestamp >= datetime('{latest}', '-{WINDOW_HOURS} hours')
    GROUP BY machine_id, machine_type
    """

    df = pd.read_sql(query, engine)

    # Temperature status against the limits of the machine's own type
    normal_max = df['machine_type'].map(
        lambda t: NORMAL_MAX_TEMP_C.get(t, DEFAULT_NORMAL_MAX_C))
    df['temp_warn_c'] = normal_max + WARN_MARGIN_C
    df['temp_crit_c'] = normal_max + CRIT_MARGIN_C
    df['efficiency_status'] = np.where(
        df['avg_temp'] > df['temp_crit_c'], 'CRITICAL',
        np.where(df['avg_temp'] > df['temp_warn_c'], 'WARNING', 'OPTIMAL'))

    # Recommendation logic
    def get_recommendation(row):
        if row['efficiency_status'] == 'CRITICAL':
            return 'IMMEDIATE_SHUTDOWN'
        elif row['failure_spike_count'] >= SPIKES_FOR_MAINTENANCE:
            return 'SCHEDULE_MAINTENANCE'
        elif row['efficiency_status'] == 'WARNING' and current_price_eur > HIGH_PRICE_EUR_MWH:
            return 'REDUCE_LOAD'
        else:
            return 'CONTINUE'

    df['recommendation'] = df.apply(get_recommendation, axis=1)
    df['energy_price_eur_mwh'] = current_price_eur
    df['window_hours'] = WINDOW_HOURS
    df['as_of'] = latest

    print("\n🏆 GOLD LAYER: OPERATIONAL PROFITABILITY")
    print(df[['machine_id', 'avg_risk_score', 'hourly_energy_cost_eur', 'recommendation']])

    df.to_sql('gold_operations_status', engine, if_exists='replace', index=False)

if __name__ == "__main__":
    generate_financial_gold()
import pandas as pd
from sqlalchemy import create_engine
from energy_api import EnergyMarketAPI

engine = create_engine('sqlite:///factory_lakehouse.db')

def generate_financial_gold():
    api = EnergyMarketAPI()
    market_data = api.get_current_price()
    current_price_eur = market_data['price']

    print(f"⚡ Current Energy Price: {current_price_eur} EUR/MWh")

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
        ROUND((AVG(power_kw) / 1000) * {current_price_eur}, 4) as hourly_energy_cost_eur,
        CASE 
            WHEN AVG(temp_c) > 100 THEN 'CRITICAL'
            WHEN AVG(temp_c) > 80  THEN 'WARNING'
            ELSE 'OPTIMAL'
        END as efficiency_status
    FROM silver_telemetry
    GROUP BY machine_id, machine_type
    """

    df = pd.read_sql(query, engine)

    # Recommendation logic
    def get_recommendation(row):
        if row['efficiency_status'] == 'CRITICAL':
            return 'IMMEDIATE_SHUTDOWN'
        elif row['failure_spike_count'] > 3:
            return 'SCHEDULE_MAINTENANCE'
        elif row['efficiency_status'] == 'WARNING' and current_price_eur > 200:
            return 'REDUCE_LOAD'
        else:
            return 'CONTINUE'

    df['recommendation'] = df.apply(get_recommendation, axis=1)
    df['energy_price_eur_mwh'] = current_price_eur

    print("\n🏆 GOLD LAYER: OPERATIONAL PROFITABILITY")
    print(df[['machine_id', 'avg_risk_score', 'hourly_energy_cost_eur', 'recommendation']])

    df.to_sql('gold_operations_status', engine, if_exists='replace', index=False)

if __name__ == "__main__":
    generate_financial_gold()
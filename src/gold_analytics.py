import pandas as pd
from sqlalchemy import create_engine
from energy_api import EnergyMarketAPI # Importing our new API

engine = create_engine('sqlite:///factory_lakehouse.db')

def generate_financial_gold():
    # 1. Get current Energy Price from our "External" Source
    api = EnergyMarketAPI()
    market_data = api.get_current_price()
    current_price_eur = market_data['price']
    
    print(f"⚡ Current Energy Price: {current_price_eur} EUR/MWh")

    # 2. Advanced SQL: Calculate Energy Cost per Machine
    # We convert kW to MWh and multiply by the current market rate
    query = f"""
    SELECT 
        machine_id,
        AVG(power_kw) as avg_power_usage,
        AVG(temp_c) as avg_temp,
        -- Calculate Hourly Cost: (kW / 1000) * Price_per_MWh
        ROUND((AVG(power_kw) / 1000) * {current_price_eur}, 4) as hourly_energy_cost_eur,
        -- Identify "Waste" if Temp is high (Inefficient cooling)
        CASE 
            WHEN AVG(temp_c) > 60 THEN 'INEFFICIENT'
            ELSE 'OPTIMAL'
        END as efficiency_status
    FROM silver_telemetry
    GROUP BY machine_id
    """
    
    df = pd.read_sql(query, engine)
    
    # 3. Add the "Profitability" recommendation
    df['recommendation'] = df.apply(
        lambda x: "SHUTDOWN" if x['efficiency_status'] == 'INEFFICIENT' and current_price_eur > 200 
        else "CONTINUE", axis=1
    )

    print("\n🏆 GOLD LAYER: OPERATIONAL PROFITABILITY")
    print(df)
    
    # Save to SQL for the Dashboard
    df.to_sql('gold_operations_status', engine, if_exists='replace', index=False)

if __name__ == "__main__":
    generate_financial_gold()
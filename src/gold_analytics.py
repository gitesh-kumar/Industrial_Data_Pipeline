import pandas as pd
from sqlalchemy import create_engine

engine = create_engine('sqlite:///factory_lakehouse.db')

def generate_gold_metrics():
    # This SQL query uses Common Table Expression to calculate the financial loss of running a vibrating/hot machine.
    gold_query = """
    WITH base_metrics AS (
        SELECT 
            machine_id,
            AVG(temp_c) as avg_temp,
            AVG(vibration_rms) as avg_vibration,
            COUNT(*) as reading_count
        FROM silver_telemetry
        WHERE quality_flag = 'PASS'
        GROUP BY machine_id
    )
    SELECT 
        machine_id,
        avg_temp,
        avg_vibration,
        -- Business Logic: Assume every 1 unit of vibration over 3.0 
        -- costs $50/hour in wasted energy and wear.
        ROUND((avg_vibration - 3.0) * 50, 2) as estimated_hourly_loss_euro
    FROM base_metrics
    WHERE avg_vibration > 3.0;
    """
    
    print("🏆 GOLD LAYER: FINANCIAL IMPACT ANALYSIS")
    df = pd.read_sql(gold_query, engine)
    
    if df.empty:
        print("All machines operating within optimal parameters.")
    else:
        print(df)
        # Saving to the table for Power BI
        df.to_sql('gold_financial_impact', engine, if_exists='replace', index=False)

if __name__ == "__main__":
    generate_gold_metrics()
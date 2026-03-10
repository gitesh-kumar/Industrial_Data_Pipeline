import pandas as pd
from sqlalchemy import create_engine

engine = create_engine('sqlite:///factory_lakehouse.db')

def run_governance_audit():
    print("🛡️ STARTING DATA GOVERNANCE AUDIT...")
    
    # 1. Check for Quarantined Records
    query_anomalies = """
    SELECT quality_flag, COUNT(*) as count 
    FROM silver_telemetry 
    GROUP BY quality_flag
    """
    
    # 2. Check for Data Freshness (How old is the latest reading?)
    query_freshness = "SELECT MAX(timestamp) as last_update FROM silver_telemetry"
    
    df_quality = pd.read_sql(query_anomalies, engine)
    df_freshness = pd.read_sql(query_freshness, engine)

    print("\n📊 DATA QUALITY SCORECARD:")
    print(df_quality)
    
    print(f"\n🕒 LATEST DATA INGESTED: {df_freshness['last_update'].iloc[0]}")
    
    # 3. Calculate "Health %"
    total = df_quality['count'].sum()
    passed = df_quality[df_quality['quality_flag'] == 'PASS']['count'].sum()
    health_score = (passed / total) * 100
    
    print(f"✅ OVERALL PIPELINE HEALTH: {health_score:.2f}%")
    
    if health_score < 90:
        print("⚠️ WARNING: Low Data Quality detected. Inspect sensors immediately.")

if __name__ == "__main__":
    run_governance_audit()
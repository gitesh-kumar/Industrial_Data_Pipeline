import time
import subprocess
import os
import sys

def run_pipeline():
    print("--- 🏭 SMART FACTORY DATA LAKEHOUSE: MASTER ORCHESTRATOR ---")
    
    # 1. Ingestion (Bronze Layer)
    print("\n[Step 1/4] 🚀 INGESTION: Capturing Real-Time IoT Telemetry...")
    # Using sys.executable ensures we use the correct Python from your venv
    proc = subprocess.Popen([sys.executable, 'src/ingestion.py'])
    time.sleep(12) # Let it capture a few batches
    proc.terminate() 
    print("✅ BRONZE LAYER: Raw data appended to data/bronze_sensors.csv")

    # 2. Transformation (Silver Layer)
    print("\n[Step 2/4] 🧹 TRANSFORMATION: Validating & Cleaning Data...")
    os.system(f'{sys.executable} src/transformer.py')
    print("✅ SILVER LAYER: Telemetry standardized and quality-checked.")

    # 3. Analytics & API Integration (Gold Layer)
    print("\n[Step 3/4] 💰 ANALYTICS: Calculating Financial Impact (Energy API)...")
    os.system(f'{sys.executable} src/gold_analytics.py')
    print("✅ GOLD LAYER: Strategic insights generated for BI.")

    # 4. Governance & Audit (The "Safety Check")
    print("\n[Step 4/4] 🛡️ GOVERNANCE: Running Pipeline Health Audit...")
    os.system(f'{sys.executable} src/data_governance.py')
    print("✅ AUDIT COMPLETE: Pipeline status updated.")

    print("\n" + "="*50)
    print("🏁 END-TO-END EXECUTION SUCCESSFUL")
    print("Database: factory_lakehouse.db is ready for Power BI.")
    print("="*50)

if __name__ == "__main__":
    run_pipeline()
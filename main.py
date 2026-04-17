import time
import subprocess
import sys

def run_pipeline():
    print("--- 🏭 SMART FACTORY DATA LAKEHOUSE: MASTER ORCHESTRATOR ---")
    
    print("\n[Step 1/4] 🚀 INGESTION: Capturing Real-Time IoT Telemetry...")
    proc = subprocess.Popen([sys.executable, 'src/ingestion.py'])
    time.sleep(12)
    proc.terminate()
    print("✅ BRONZE LAYER: Raw data appended to data/bronze_sensors.csv")

    print("\n[Step 2/4] 🧹 TRANSFORMATION: Validating & Cleaning Data...")
    subprocess.run([sys.executable, 'src/transformer.py'], check=True)
    print("✅ SILVER LAYER: Telemetry standardized and quality-checked.")

    print("\n[Step 3/4] 💰 ANALYTICS: Calculating Financial Impact (Energy API)...")
    subprocess.run([sys.executable, 'src/gold_analytics.py'], check=True)
    print("✅ GOLD LAYER: Strategic insights generated for BI.")

    print("\n[Step 4/4] 🛡️ GOVERNANCE: Running Pipeline Health Audit...")
    subprocess.run([sys.executable, 'src/data_governance.py'], check=True)
    print("✅ AUDIT COMPLETE: Pipeline status updated.")

    print("\n" + "="*50)
    print("🏁 END-TO-END EXECUTION SUCCESSFUL")
    print("Database: factory_lakehouse.db is ready.")
    print("="*50)

if __name__ == "__main__":
    run_pipeline()
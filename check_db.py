import sqlite3
import pandas as pd

# Connect to your Lakehouse
conn = sqlite3.connect('factory_lakehouse.db')

# Check if the Gold Financial table exists and has data
try:
    df = pd.read_sql_query("SELECT * FROM gold_financial LIMIT 5", conn)
    print("✅ Database Connection: SUCCESS")
    print("📊 Sample Gold Layer Data:")
    print(df)
    
    # Check for the key column the AI will need
    if 'estimated_hourly_loss_euro' in df.columns:
        print("\n💰 Financial Columns: FOUND. The AI can calculate costs.")
    else:
        print("\n⚠️ Warning: Financial columns missing. Check your transformation logic.")
        
except Exception as e:
    print(f"❌ Error: {e}")
finally:
    conn.close()
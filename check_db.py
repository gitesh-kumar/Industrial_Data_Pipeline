import sqlite3
import pandas as pd

conn = sqlite3.connect('factory_lakehouse.db')

try:
    df = pd.read_sql_query("SELECT * FROM gold_operations_status LIMIT 5", conn)
    print("✅ Database Connection: SUCCESS")
    print("📊 Sample Gold Layer Data:")
    print(df)
    print(f"\n✅ Tables found: {df.shape[0]} records, {df.shape[1]} columns")
except Exception as e:
    print(f"❌ Error: {e}")
finally:
    conn.close()
import sqlite3
db = "G:/tdx_data/tdx_daily.db"
conn = sqlite3.connect(db, timeout=5)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)
print("Has daily_kline:", "daily_kline" in tables)
print("Has stock_names:", "stock_names" in tables)
conn.close()

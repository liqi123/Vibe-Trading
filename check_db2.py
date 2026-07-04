import sqlite3

db_path = r"G:\tdx_data\tdx_daily.db"
print(f"Checking: {db_path}")
conn = sqlite3.connect(db_path, timeout=10)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"Tables: {tables}")
print(f"Has daily_kline: {'daily_kline' in tables}")
print(f"Has stock_names: {'stock_names' in tables}")
if 'stock_names' in tables:
    cur.execute("SELECT COUNT(*) FROM stock_names")
    print(f"stock_names count: {cur.fetchone()[0]}")
if 'daily_kline' in tables:
    cur.execute("SELECT COUNT(*) FROM daily_kline")
    print(f"daily_kline count: {cur.fetchone()[0]}")
conn.close()

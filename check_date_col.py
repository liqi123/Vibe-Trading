import sqlite3
db = "G:/tdx_data/tdx_daily.db"
conn = sqlite3.connect(db, timeout=5)
cur = conn.cursor()
# Check if there's a 'date' column or just 'trade_date'
cur.execute("PRAGMA table_info(daily_kline)")
cols = {r[1]: r[2] for r in cur.fetchall()}
print("Columns:", cols)
print("Has 'date':", 'date' in cols)
print("Has 'trade_date':", 'trade_date' in cols)

# Check if there's a view
cur.execute("SELECT name FROM sqlite_master WHERE type='view'")
views = [r[0] for r in cur.fetchall()]
print("Views:", views)

# Try the query that sector_utils uses
try:
    cur.execute("SELECT code, date, close FROM daily_kline LIMIT 1")
    print("date column works")
except Exception as e:
    print(f"date column error: {e}")

try:
    cur.execute("SELECT code, trade_date, close FROM daily_kline LIMIT 1")
    print("trade_date column works")
except Exception as e:
    print(f"trade_date column error: {e}")

# Check stock_finance
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)
print("Has stock_finance:", 'stock_finance' in tables)
conn.close()

import sqlite3
db = "G:/tdx_data/tdx_daily.db"
conn = sqlite3.connect(db, timeout=5)
cur = conn.cursor()
# Check daily_kline columns
cur.execute("PRAGMA table_info(daily_kline)")
print("daily_kline columns:", [(r[1], r[2]) for r in cur.fetchall()])
# Check all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("All tables:", tables)
# Check if stock_finance exists
if 'stock_finance' in tables:
    cur.execute("PRAGMA table_info(stock_finance)")
    print("stock_finance columns:", [(r[1], r[2]) for r in cur.fetchall()])
else:
    print("stock_finance does NOT exist")
# Check stock_names columns
if 'stock_names' in tables:
    cur.execute("PRAGMA table_info(stock_names)")
    print("stock_names columns:", [(r[1], r[2]) for r in cur.fetchall()])
    cur.execute("SELECT * FROM stock_names LIMIT 2")
    print("stock_names sample:", cur.fetchall())
# Check latest date
cur.execute("SELECT MAX(trade_date) FROM daily_kline")
print("Latest trade_date:", cur.fetchone()[0])
conn.close()

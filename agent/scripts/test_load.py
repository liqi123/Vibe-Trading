"""Test SQLite query speed for 2026."""
import sqlite3, time
db = r'G:\tdx_data\tdx_daily.db'
conn = sqlite3.connect(db)
t0 = time.time()
cur = conn.execute("SELECT COUNT(*) FROM daily_kline WHERE trade_date >= 20260101 AND trade_date <= 20260701")
n = cur.fetchone()[0]
print(f"Rows in 2026: {n} ({time.time()-t0:.1f}s)")

t0 = time.time()
cur = conn.execute("SELECT COUNT(DISTINCT code) FROM daily_kline WHERE trade_date >= 20260101 AND trade_date <= 20260701")
n = cur.fetchone()[0]
print(f"Stocks in 2026: {n} ({time.time()-t0:.1f}s)")
conn.close()

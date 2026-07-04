import sqlite3
db = "G:/tdx_data/tdx_daily.db"
conn = sqlite3.connect(db, timeout=5)
cur = conn.cursor()
cur.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='stocks'")
row = cur.fetchone()
print("stocks view:", row[0] if row else "NOT FOUND")
cur.execute("PRAGMA table_info(stock_names)")
print("stock_names cols:", [r[1] for r in cur.fetchall()])
conn.close()

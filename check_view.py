import sqlite3
db = "G:/tdx_data/tdx_daily.db"
conn = sqlite3.connect(db, timeout=5)
cur = conn.cursor()
# Check the stocks view
cur.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='stocks'")
print("stocks view DDL:", cur.fetchone()[0])
cur.execute("SELECT * FROM stocks LIMIT 3")
print("stocks sample:", cur.fetchall())
# Check stock_names
cur.execute("PRAGMA table_info(stock_names)")
print("stock_names cols:", [(r[1], r[2]) for r in cur.fetchall()])
cur.execute("SELECT * FROM stock_names LIMIT 3")
print("stock_names sample:", cur.fetchall())
# Check auction
cur.execute("PRAGMA table_info(auction)")
print("auction cols:", [(r[1], r[2]) for r in cur.fetchall()])
conn.close()

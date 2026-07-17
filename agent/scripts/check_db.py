import sqlite3
db = r'G:\tdx_data\tdx_daily.db'
conn = sqlite3.connect(db)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=OFF")
cur = conn.execute("SELECT trade_date FROM daily_kline ORDER BY trade_date DESC LIMIT 1")
row = cur.fetchone()
print(f"Max date: {row[0] if row else 'none'}")
cur = conn.execute("SELECT trade_date FROM daily_kline ORDER BY trade_date ASC LIMIT 1")
row = cur.fetchone()
print(f"Min date: {row[0] if row else 'none'}")
conn.close()

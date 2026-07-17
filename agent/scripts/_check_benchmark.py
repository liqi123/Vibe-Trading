"""Check database for benchmark index data."""
import sqlite3
conn = sqlite3.connect(r"G:\tdx_data\tdx_daily.db")
cur = conn.execute("SELECT DISTINCT code FROM daily_kline WHERE code LIKE 'SH000001' OR code LIKE 'SH000300' OR code LIKE 'SH000905' OR code LIKE 'SZ399001' OR code LIKE 'SZ399300' OR code LIKE 'SH000016' OR code LIKE 'SH000688' LIMIT 20")
for r in cur.fetchall():
    print(r[0])
print("---")
# also check for CSI all-share
cur2 = conn.execute("SELECT DISTINCT code FROM daily_kline WHERE code LIKE 'SH_____' AND code != 'SH000001' LIMIT 20")
for r in cur2.fetchall():
    print(r[0])
conn.close()

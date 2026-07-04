import sys
sys.path.insert(0, 'C:/Users/XYXS/trading')
from utils.config import DB_PATH
print('DB_PATH:', DB_PATH)
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables)
print('Has stock_names:', 'stock_names' in tables)
if 'stock_names' in tables:
    cur.execute("SELECT COUNT(*) FROM stock_names")
    print('stock_names count:', cur.fetchone()[0])
conn.close()

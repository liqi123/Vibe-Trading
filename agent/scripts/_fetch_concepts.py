"""抓取个股东财概念标签 → 概念数量因子数据库。

数据源: 东财概念板块(m:90+t:3) 495个概念 + 分页。
输出: G:\tdx_data\tdx_daily.db 的 concept_count 表

用法: python scripts/_fetch_concepts.py
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fetch_concepts")

DB = r"G:\tdx_data\tdx_daily.db"
BASE = "https://push2.eastmoney.com/api/qt/clist/get"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _req(params: dict, sess: requests.Session, max_retries=3) -> dict:
    for attempt in range(max_retries):
        try:
            r = sess.get(BASE, params=params, timeout=15)
            return r.json()
        except Exception as e:
            log.warning("  retry %d: %s", attempt + 1, e)
            time.sleep(2)
    return {}


def _paginate_all(fs: str, fields: str, sess: requests.Session, page_size=200) -> list[dict]:
    """Fetch ALL pages for given filter string."""
    all_items = []
    pn = 1
    while True:
        params = {"pn": pn, "pz": page_size, "po": 1, "np": 1,
                  "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                  "fltt": 2, "invt": 2, "fid": "f3",
                  "fs": fs, "fields": fields}
        data = _req(params, sess)
        if not data:
            break
        diff = data.get("data", {}).get("diff", [])
        if not diff:
            break
        all_items.extend(diff if isinstance(diff, list) else diff.values())
        total = data.get("data", {}).get("total", 0)
        if pn * page_size >= total:
            break
        pn += 1
        time.sleep(0.15)
    return all_items


def main():
    sess = requests.Session()
    sess.headers.update(HEADERS)

    log.info("Step 1: Fetching ALL concept boards ...")
    boards = _paginate_all("m:90+t:3", "f12,f14,f20", sess, page_size=200)
    log.info("  Found %d concepts", len(boards))

    code_concepts: dict[str, set[str]] = {}

    for i, board in enumerate(boards):
        bcode = board.get("f12", "")
        bname = board.get("f14", "")
        if not bcode:
            continue

        stocks = _paginate_all(f"b:{bcode}+f:!50", "f12", sess, page_size=500)
        if not stocks:
            continue
        for s in stocks:
            scode = s.get("f12", "")
            if scode and len(scode) == 6:
                code_concepts.setdefault(scode, set()).add(bname)

        if (i + 1) % 50 == 0:
            log.info("  Processed %d/%d boards, %d stocks mapped", i + 1, len(boards), len(code_concepts))

    log.info("Total stocks with concepts: %d", len(code_concepts))
    log.info("Total concept boards: %d", len(boards))

    # Write to DB
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS concept_count (
            code TEXT PRIMARY KEY,
            count INTEGER,
            concepts TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("DELETE FROM concept_count")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for code, concepts_set in code_concepts.items():
        conn.execute(
            "INSERT OR REPLACE INTO concept_count (code, count, concepts, updated_at) VALUES (?, ?, ?, ?)",
            (code, len(concepts_set), json.dumps(list(concepts_set), ensure_ascii=False), now),
        )
    conn.commit()
    conn.close()
    log.info("Saved %d stock concept counts to DB", len(code_concepts))

    counts = [len(v) for v in code_concepts.values()]
    log.info("Stats: min=%d max=%d mean=%.1f median=%d",
             min(counts), max(counts), pd.Series(counts).mean(), int(pd.Series(counts).median()))


if __name__ == "__main__":
    main()

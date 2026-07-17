from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.factors.base import safe_div

__alpha_meta__ = {
    "id": "my_sentiment_benchmark",
    "nickname": "市场情绪 count(stock_up & bench_down, 50) / count(bench_down, 50)",
    "theme": ["sentiment", "momentum"],
    "formula_latex": "COUNT(close>open & bench<delay(bench,1), 50) / COUNT(bench<delay(bench,1), 50)",
    "columns_required": ["close", "open"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 50,
    "min_warmup_bars": 50,
    "notes": "GTJA #075, 使用 sh000001 上证指数作为真实大盘基准。大盘跌的日子中个股涨的比例。值高=个股强势。",
}

def _load_benchmark(dates) -> pd.Series:
    db = r"G:\tdx_data\tdx_daily.db"
    conn = sqlite3.connect(db)
    date_strs = [d.strftime("%Y%m%d") for d in dates]
    ph = ",".join(["?"] * len(date_strs))
    cur = conn.execute(f"SELECT trade_date, close FROM daily_kline WHERE code='sh000001' AND trade_date IN ({ph})", date_strs)
    rows = cur.fetchall()
    conn.close()
    s = pd.Series({pd.Timestamp(str(r[0])): float(r[1]) for r in rows}, dtype=float)
    s = s.reindex(dates).ffill()
    return s

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    o = panel["open"].astype(float)

    bench = _load_benchmark(c.index)
    bench_prev = bench.shift(1)

    bench_down = (bench < bench_prev).astype(float)
    stock_up = (c > o).astype(float)

    up_and_down = stock_up * bench_down.values[:, None]

    num = up_and_down.rolling(50, min_periods=30).sum()
    den = pd.DataFrame(
        np.broadcast_to(bench_down.values[:, None], c.shape),
        index=c.index, columns=c.columns,
    ).rolling(50, min_periods=30).sum()

    return safe_div(num, den)

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "my_open_vs_vwap",
    "nickname": "开盘VWAP偏离 — rank(open - MA(vwap,10)) × -rank(|close - vwap|)",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK(open - MA(vwap,10)) * (-1 * RANK(ABS(close - vwap)))",
    "columns_required": ["open", "close", "volume", "amount"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 10,
    "min_warmup_bars": 11,
    "notes": "GTJA #012. 开盘价相对10日均VWAP的偏离 × 收盘VWAP偏离绝对值的负rank。开盘高于均线+收盘接近VWAP=强势；开盘低于均线+收盘远离VWAP=弱势。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"]
    c = panel["close"]
    v = panel["volume"]
    a = panel["amount"]
    vwap = a / v.replace(0, np.nan)
    open_div = o - ts_mean(vwap, 10)
    close_dev = (c - vwap).abs()
    return rank(open_div) * (-1.0 * rank(close_dev))

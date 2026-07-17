from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_max, ts_min

__alpha_meta__ = {
    "id": "my_vwap_range_position",
    "nickname": "VWAP区间位置 — rank(vwap - max(15)) + rank(vwap - min(15))",
    "theme": ["reversal"],
    "formula_latex": "RANK(vwap - TS_MAX(vwap, 15)) + RANK(vwap - TS_MIN(vwap, 15))",
    "columns_required": ["close", "volume", "amount"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 15,
    "min_warmup_bars": 16,
    "notes": "GTJA #017 简化版。VWAP相对15日高点的距离(distance below peak, ≤0)和低点的距离。合起来衡量VWAP在15日区间中的位置。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    a = panel["amount"]
    vwap = a / v.replace(0, np.nan)
    dist_high = vwap - ts_max(vwap, 15)
    dist_low = vwap - ts_min(vwap, 15)
    return rank(dist_high) + rank(dist_low)

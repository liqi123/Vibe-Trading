from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_max

__alpha_meta__ = {
    "id": "my_ts_drawdown",
    "nickname": "距高点距离 — rank(close / max(close,20))",
    "theme": ["reversal"],
    "formula_latex": "RANK(close / TS_MAX(close, 20))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 20,
    "notes": "时序因子。收盘价距离20日最高点的比例。值低=接近底部(超卖)→买入; 值高=接近顶部(超买)→卖出。与截面MA回归不同。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ratio = c / ts_max(c, 20)
    return rank(ratio)

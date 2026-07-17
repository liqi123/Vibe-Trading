from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_ts_streak",
    "nickname": "连涨天数 — -rank(连续上涨天数)",
    "theme": ["reversal", "momentum"],
    "formula_latex": "-1 * RANK(consecutive_up_days)",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 20,
    "notes": "时序因子。统计连续上涨的天数(close>prev_close)，越长越可能反转下跌。非截面，每只股票独立计算自己的连涨天数。",
}

def _streak(close: pd.DataFrame) -> pd.DataFrame:
    up = (close > close.shift(1)).astype(int)
    streak = up.copy()
    for i in range(1, len(up)):
        streak.iloc[i] = (streak.iloc[i-1] + 1) * up.iloc[i]
    return streak

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    s = _streak(c)
    return -1.0 * rank(s)

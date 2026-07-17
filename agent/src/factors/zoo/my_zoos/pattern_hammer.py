from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_pattern_hammer",
    "nickname": "锤子线 — rank(下影线/(h-l)) × -sign(prior_trend)",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK((min(o,c)-l)/(h-l)) * -1 * SIGN(close-delay(close,1))",
    "columns_required": ["open", "high", "low", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 2,
    "min_warmup_bars": 5,
    "notes": "K线形态。锤子线(长下影线+小实体)出现在下跌后表示底部反转。值高=下跌趋势中长下影线→看多反转。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    rng = (h - l).replace(0, np.nan)
    lower_wick = (o.where(o < c, c) - l)
    upper_wick = (h - o.where(o > c, c))
    hammer = lower_wick / rng
    shooting = upper_wick / rng
    prior_trend = (c - c.shift(1))
    return rank(hammer) * -1.0 * prior_trend

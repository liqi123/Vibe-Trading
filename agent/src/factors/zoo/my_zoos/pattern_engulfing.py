from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_pattern_engulfing",
    "nickname": "吞没形态 — rank(今日范围/昨日范围) × direction",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK((h-l)/(delay(h,1)-delay(l,1))) * SIGN(close-open)",
    "columns_required": ["open", "high", "low", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 2,
    "min_warmup_bars": 5,
    "notes": "K线形态。今日阳线范围完全覆盖昨日阴线范围(看涨吞没)或反之(看跌吞没)。范围扩张比越大信号越强。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    today_range = h - l
    prev_range = (h.shift(1) - l.shift(1)).replace(0, np.nan)
    expansion = today_range / prev_range
    direction = c - o
    return rank(expansion) * direction

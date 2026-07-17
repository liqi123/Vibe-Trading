from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_intraday_reversal",
    "nickname": "日内反转 — -rank((close-open)/open) × rank(vol/MA5)",
    "theme": ["reversal", "volume"],
    "formula_latex": "-1 * RANK((close - open) / open) * RANK(volume / MA(volume, 5))",
    "columns_required": ["close", "open", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "日内收益取负 × 成交量5日相对强度。大涨+放量→负值(次日反转看空)；"
        "大跌+放量→正值(恐慌释放看多)。纯OHLCV，无NaN问题。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    o = panel["open"]
    v = panel["volume"]
    intraday_ret = (c - o) / o.replace(0, np.nan)
    vol_ratio = v / v.rolling(5).mean()
    return -1.0 * rank(intraday_ret) * rank(vol_ratio)

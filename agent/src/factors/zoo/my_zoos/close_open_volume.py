from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_close_open_volume",
    "nickname": "收盘强度 — rank(close/open) × rank(vol/MA20)",
    "theme": ["volume", "reversal"],
    "formula_latex": "RANK(close / open) * RANK(volume / MA(volume, 20))",
    "columns_required": ["close", "open", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "收盘/开盘比(日内强度) × 成交量20日相对强度。"
        "高收盘强度+放量=强趋势延续；高收盘强度+缩量=趋势减弱。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    o = panel["open"]
    v = panel["volume"]
    strength = c / o.replace(0, np.nan)
    vol_ratio = v / v.rolling(20).mean()
    return rank(strength) * rank(vol_ratio)

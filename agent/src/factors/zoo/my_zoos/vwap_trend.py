from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_vwap_trend",
    "nickname": "VWAP趋势 — rank(close/vwap) × 5日均值",
    "theme": ["momentum", "microstructure"],
    "formula_latex": "RANK(MA(close / VWAP, 5))",
    "columns_required": ["close", "vwap"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "收盘价/VWAP 的 5 日均值，cross-sectional rank。"
        "持续高于VWAP = 日内趋势强势；持续低于 = 弱势。"
        "比单日偏离更稳定。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["vwap"]
    ratio = c / v.replace(0, np.nan)
    trend = ratio.rolling(5).mean()
    return rank(trend)

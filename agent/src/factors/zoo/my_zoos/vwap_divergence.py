from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_vwap_divergence",
    "nickname": "VWAP偏离 — rank((close - vwap) / close)",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK((close - VWAP) / close)",
    "columns_required": ["close", "vwap"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "收盘价相对VWAP的偏离度。正值=收盘高于均价(日内强势)；"
        "负值=收盘低于均价(日内弱势)。均值回归预期。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["vwap"]
    div = (c - v) / c.replace(0, np.nan)
    return rank(div)

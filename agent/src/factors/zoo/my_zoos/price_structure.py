from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_price_structure",
    "nickname": "多均线结构 — (MA3+MA6+MA12+MA24)/(4×close)",
    "theme": ["reversal"],
    "formula_latex": "RANK((MA3 + MA6 + MA12 + MA24) / (4 * close))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 24,
    "min_warmup_bars": 25,
    "notes": (
        "GTJA #046 移植。四均线均值 / 收盘价。比值>1=价格低于均线(超卖)，<1=价格高于均线(超买)。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    ma3 = c.rolling(3).mean()
    ma6 = c.rolling(6).mean()
    ma12 = c.rolling(12).mean()
    ma24 = c.rolling(24).mean()
    ratio = (ma3 + ma6 + ma12 + ma24) / (4.0 * c)
    return rank(ratio)

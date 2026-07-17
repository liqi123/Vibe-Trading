from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_volume_ratio_reversal",
    "nickname": "成交量比反转 — -rank(volume/MA20)",
    "theme": ["volume", "reversal"],
    "formula_latex": "-1 * RANK(volume / MA(volume, 20))",
    "columns_required": ["volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "GTJA #168 移植。当日量 / 20日均量，取负。放量>1 看空，缩量<1 看多。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    v = panel["volume"]
    ratio = v / v.rolling(20).mean()
    return -1.0 * rank(ratio)

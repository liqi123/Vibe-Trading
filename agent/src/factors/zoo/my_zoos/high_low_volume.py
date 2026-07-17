from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_high_low_volume",
    "nickname": "振幅量比 — rank(high/low) × rank(vol/MA5)",
    "theme": ["volume", "volatility"],
    "formula_latex": "RANK(high / low) * RANK(volume / MA(volume, 5))",
    "columns_required": ["high", "low", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "日内振幅(高/低) × 成交量5日相对强度。"
        "高振幅+放量=多空分歧大 → 短期反转概率高。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"]
    l = panel["low"]
    v = panel["volume"]
    amp = h / l.replace(0, np.nan)
    vol_ratio = v / v.rolling(5).mean()
    return rank(amp) * rank(vol_ratio)

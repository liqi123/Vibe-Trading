# ============================================================
# 中文名称: 量价加速度背离
# 简要说明: 价格加速度与成交量变化方向的背离程度。
#           价格加速上涨时缩量 -> 做空（负值），
#           价格加速上涨时放量 -> 做多（正值）。
# 典型用途: 识别趋势中的动能衰减与放量突破。
# ============================================================
"""Momentum-Volume Divergence Factor.

Measures whether price acceleration is confirmed by volume.
Positive = volume confirms price acceleration (bullish).
Negative = volume diverges from price acceleration (bearish).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_corr, ts_mean, ts_std, rank

__alpha_meta__ = {
    "id": "my_mom_vol_divergence",
    "theme": ["momentum", "volume"],
    "formula_latex": (
        "Z(ROC(close,5) - ROC(close,10)) * "
        "sign(CORR(ROC(close,5), volume, 10))"
    ),
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn", "equity_us"],
    "frequency": ["1d"],
    "decay_horizon": 10,
    "min_warmup_bars": 15,
    "notes": (
        "Positive when short-term momentum is accelerating AND volume "
        "is positively correlated with price change. Negative when "
        "momentum accelerates on shrinking volume (divergence)."
    ),
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]

    roc5 = c.pct_change(5)
    roc10 = c.pct_change(10)

    accel = roc5 - roc10
    vol_corr = ts_corr(roc5, v, 10)

    signal = accel * vol_corr

    return signal

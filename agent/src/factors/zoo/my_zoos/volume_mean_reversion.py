from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_volume_mean_reversion",
    "nickname": "量均值回归 — rank(close/MA5) × -rank(vol/MA20)",
    "theme": ["volume", "reversal"],
    "formula_latex": "RANK(close / MA(close, 5)) * -1 * RANK(volume / MA(volume, 20))",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "my_volume_ratio_reversal 的动量增强版。涨幅高+放量→负值(反转做空)；"
        "涨幅高+缩量→正值(趋势延续)；跌幅大+放量→正值(恐慌释放)。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    mom = c / c.rolling(5).mean()
    vol_ratio = v / v.rolling(20).mean()
    return rank(mom) * (-1.0 * rank(vol_ratio))

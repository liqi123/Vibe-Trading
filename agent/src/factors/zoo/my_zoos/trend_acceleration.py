from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_mean, delta

__alpha_meta__ = {
    "id": "my_trend_acceleration",
    "nickname": "趋势加速度 — SMA((close-MA6)/MA6 - delay((close-MA6)/MA6, 3), 12)",
    "theme": ["reversal"],
    "formula_latex": "SMA((close-MA6)/MA6 - DELAY((close-MA6)/MA6, 3), 12, 1)",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 12,
    "min_warmup_bars": 18,
    "notes": "GTJA #022. 价格相对6日均线偏离度的3日变化，再用12日SMA平滑。捕捉趋势加速度变化。正值=加速偏离(趋势末端)，负值=均值回归。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    ma6 = c.rolling(6).mean()
    dev = (c - ma6) / ma6
    accel = dev - dev.shift(3)
    sma = accel.rolling(12, min_periods=4).mean()
    return rank(sma)

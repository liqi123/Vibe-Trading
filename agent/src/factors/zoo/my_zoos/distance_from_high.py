from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_distance_from_high",
    "nickname": "距高点距离 — rank(close / max(close, 20))",
    "theme": ["reversal", "momentum"],
    "formula_latex": "RANK(close / TS_MAX(close, 20))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "收盘价相对于20日最高点的位置。接近高点(值接近1)=上方阻力大→看空；"
        "远离高点(值低)=下跌后有反弹空间→看多。均值回归逻辑。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    high_20 = c.rolling(20).max()
    ratio = c / high_20
    return rank(ratio)

"""OBV趋势强度因子

信号：OBV(On-Balance Volume)累积成交量线 vs 其20日均线的偏离程度。
OBV > 均线=资金持续流入; OBV < 均线=流出。反映量能趋势与价格趋势的协同。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_obv_trend",
    "nickname": "OBV趋势强度 — OBV/MA(OBV,20)偏离",
    "theme": ["volume", "momentum"],
    "formula_latex": "RANK(OBV / MA(OBV, 20) - 1)",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "OBV累积成交量线，反映资金流入流出的累积效应。"
        "OBV > 20日均线=资金持续流入。OBV上升但价格横盘=吸筹信号(积累阶段)。"
        "OBV下降但价格横盘=派发信号(出货阶段)。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    direction = np.sign(c.diff())
    obv = (direction * v).cumsum()
    obv_ma = obv.rolling(20).mean()
    return rank(obv / obv_ma - 1)

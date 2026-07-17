"""日内强度因子

信号：收盘价在当日高低区间内的百分位。接近1=强势收盘(动量延续可能);
接近0=弱势收盘(次日低开可能)。A股尾盘拉升/砸盘现象明显，此因子捕捉该效应。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "my_intraday_intensity",
    "nickname": "日内强度 — 收盘在日线区间的位置",
    "theme": ["microstructure", "reversal"],
    "formula_latex": "RANK((close - low) / (high - low))",
    "columns_required": ["high", "low", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "收盘价在当日高低区间内的百分位(Close Location Value)。"
        "接近1=尾盘强势收盘(动量延续可能); 接近0=尾盘弱势收盘(次日低开可能)。"
        "A股尾盘30分钟操纵效应明显，该因子可捕捉收盘阶段资金意图。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    hl = h - l
    intensity = safe_div(c - l, hl)
    return rank(intensity)

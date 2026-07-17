"""A/D线(Accumulation/Distribution)趋势因子

信号：A/D线 = 累积((C-L)-(H-C))/(H-L)×V。CLV正=资金在吸筹(收盘近高点);
CLV负=资金在派发(收盘近低点)。A/D线趋势强度通过当前值/20日均线衡量。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "my_accdist",
    "nickname": "A/D线趋势 — Accumulation/Distribution",
    "theme": ["volume", "sentiment"],
    "formula_latex": "RANK(CLV × V / MA(CLV×V, 20) - 1)",
    "columns_required": ["high", "low", "close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "A/D线 = 累积((C-L)-(H-C))/(H-L)×Volume。CLV(Close Location Value)衡量"
        "收盘在当日区间的相对位置。A/D上升而价格下跌=积累(底背离)→看多。"
        "A/D下降而价格上涨=派发(顶背离)→看空。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    hl = h - l
    clv = safe_div((c - l) - (h - c), hl)
    ad = (clv * v).cumsum()
    ad_ma = ad.rolling(20).mean()
    return rank(ad / ad_ma - 1)

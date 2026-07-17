"""资金流指数MFI(14)因子

信号：Money Flow Index (价量结合的RSI)。TP=(H+L+C)/3; MF=TP×V。
14日内正/负资金流之比。>80超买→卖出风险; <20超卖→买入机会。
MFI区分了上涨有量vs上涨无量，比RSI更准确。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_mfi_14d",
    "nickname": "资金流指数MFI(14) — 价量结合的RSI",
    "theme": ["volume", "reversal"],
    "formula_latex": "RANK(100 - 100 / (1 + pos_mf / neg_mf))",
    "columns_required": ["high", "low", "close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 14,
    "min_warmup_bars": 15,
    "notes": (
        "Money Flow Index。TP=(H+L+C)/3; MF=TP×V。14日内正负资金流之比转为0-100指数。"
        "与RSI的区别在于MFI考虑了成交量。上涨但缩量=MFI低于RSI=假突破警示。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    tp = (h + l + c) / 3.0
    mf = tp * v
    tp_diff = tp.diff()
    pos_mf = mf * (tp_diff > 0).astype(float)
    neg_mf = mf * (tp_diff < 0).astype(float)
    pos_sum = pos_mf.rolling(14).sum()
    neg_sum = neg_mf.rolling(14).sum()
    ratio = pos_sum / neg_sum.replace(0, 1e-10)
    mfi = 100.0 - 100.0 / (1.0 + ratio)
    return rank(mfi)

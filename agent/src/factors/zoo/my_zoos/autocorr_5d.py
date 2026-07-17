"""5日收益率自相关因子

信号：5日滚动滞后1期自相关。正值=短期趋势延续(动量); 负值=频繁反转。
A股短期自相关偏负(日线反转效应)，高负自相关股票次日反转概率更大。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_autocorr_5d",
    "nickname": "5日自相关 — 收益率序列滞后1期相关性",
    "theme": ["momentum", "reversal"],
    "formula_latex": "RANK(COV(ret, ret_1) / VAR(ret))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "5日滚动滞后1期自相关。正值=过去5天收益正自相关(趋势延续)。"
        "负值=收益频繁反转(均值回复)。A股日线普遍负自相关，极端负值=强反转信号。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ret = c.pct_change()
    ret_1 = ret.shift(1)
    cov = ret.rolling(5).cov(ret_1)
    var = ret.rolling(5).var()
    ac = cov / var.replace(0, 1e-10)
    return rank(ac)

"""20日收益率偏度因子

信号：20日滚动偏度。正偏=右尾厚(偶有暴涨)→回落风险; 负偏=左尾厚(偶有暴跌)→反弹机会。
A股负偏股票有超跌反弹效应。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_skewness_20d",
    "nickname": "20日收益偏度 — 收益率分布不对称性",
    "theme": ["volatility", "reversal"],
    "formula_latex": "RANK(E[(r-μ)^3] / σ^3)",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "20日滚动偏度。正偏=尾部有极端正收益(偶发暴涨)，后续回落概率大。"
        "负偏=尾部有极端负收益(偶发暴跌)，超跌反弹概率大。截面rank。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ret = c.pct_change()
    mu = ret.rolling(20).mean()
    sigma = ret.rolling(20).std(ddof=0)
    skew = ((ret - mu) ** 3).rolling(20).mean() / (sigma ** 3 + 1e-10)
    return rank(skew)

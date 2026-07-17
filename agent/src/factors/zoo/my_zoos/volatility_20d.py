"""20日波动率因子

信号：20日滚动波动率(STD of daily returns)。截面rank。
低波动异象(Low Vol Anomaly): 低波动组合长期跑赢高波动组合。
A股高波动=妖股特征(高风险高弹性)，低波动=稳定性价值。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_volatility_20d",
    "nickname": "20日波动率 — 截面波动率因子",
    "theme": ["volatility", "momentum"],
    "formula_latex": "RANK(STD(ret, 20))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "20日滚动波动率。低波动异象(Low Vol Anomaly): 低波动组合长期跑赢高波动组合。"
        "A股中高波动股票往往是游资/题材股(连板/妖股)，低波动多为机构重仓/蓝筹。"
        "与Beta因子配合使用可构建纯波动率因子(波动率中性化Beta)。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ret = c.pct_change()
    vol = ret.rolling(20).std()
    return rank(vol)

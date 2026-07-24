"""融资情绪 v2 — 改进数据处理

改进：
1. 使用融资余额绝对值而非变化率（减少NaN）
2. 市值中性化：融资余额/市值
3. 动量确认：close/MA20 > 1

原版94.7% NaN是因为margin_change字段覆盖不足。
改用融资余额绝对值+市值中性化，覆盖更多股票。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, zscore

__alpha_meta__ = {
    "id": "my_margin_sentiment_v2",
    "nickname": "融资情绪 v2 — 余额/市值 × 动量",
    "theme": ["sentiment"],
    "formula_latex": "RANK(margin_balance / mcap) * RANK(close/MA20)",
    "columns_required": ["close", "fund:margin_balance", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "融资余额/市值 = 融资杠杆强度。市值中性化后，"
        "高杠杆+趋势向上=看多（杠杆资金顺势）；"
        "高杠杆+趋势向下=看空（杠杆资金逆势）。"
        "原版用变化率NaN太多，改用绝对值。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    margin = panel["fund:margin_balance"]
    mcap = panel["fund:mcap_yi"]
    c = panel["close"]

    # 融资杠杆强度：余额/市值
    leverage = margin / mcap.replace(0, pd.NA)
    leverage_rank = rank(leverage)

    # 动量确认
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)

    return leverage_rank * mom

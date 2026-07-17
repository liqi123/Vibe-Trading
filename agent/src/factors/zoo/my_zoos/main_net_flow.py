"""主力净流入强度因子

信号：当日主力净流入额 / 成交额（即主力资金强度占比）
正值 = 主力资金净流入占比高（看多）
负值 = 主力资金净流出占比高（看空）
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_main_net_flow",
    "nickname": "主力净流入强度 — 个股资金流主力净额/成交额",
    "theme": ["sentiment", "volume"],
    "formula_latex": (
        "RANK(main_net_flow / amount)"
    ),
    "columns_required": ["fund:main_net_flow", "amount"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 1,
    "notes": (
        "主力净流入强度 = 主力净流入额 / 当日成交金额。"
        "反映主力资金在个股交易中的参与强度。"
        "正值越高，说明主力资金主导买入；负值越低说明主力主导卖出。"
        "每日 cross-sectional rank 归一化。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["amount"]
    f = panel["fund:main_net_flow"]
    ratio = f / c
    return rank(ratio)

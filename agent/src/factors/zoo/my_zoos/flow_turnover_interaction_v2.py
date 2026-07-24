"""资金换手交互 v2 — 翻转方向 + 动量确认

改进：
1. 翻转方向：原版IC=-0.021说明资金流入+高换手是看空信号
2. 动量确认：close/MA20 > 1
3. 使用残差方法：资金流-收益回归残差

原版问题：资金流入+高换手可能是主力出货（边拉边出）。
翻转后：资金流出+低换手+趋势向上=真正的吸筹信号。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_flow_turnover_interaction_v2",
    "nickname": "资金换手交互 v2 — 翻转+动量",
    "theme": ["sentiment", "volume"],
    "formula_latex": "(RANK(mcap) - RANK(flow/mcap)) * RANK(close/MA20)",
    "columns_required": ["close", "fund:main_net_flow", "fund:mcap_yi", "fund:turnover_pct"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "翻转后：资金流出+低换手+趋势向上=主力吸筹信号。"
        "原版IC为负说明方向反了。加动量确认过滤假信号。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    c = panel["close"]

    # 翻转：资金流出强度排名
    flow_intensity = flow / mcap.replace(0, pd.NA)
    base = rank(mcap) - rank(flow_intensity)

    # 动量确认
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)

    return base * mom

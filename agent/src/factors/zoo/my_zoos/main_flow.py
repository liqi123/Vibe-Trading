"""主力资金流强度因子（改进版）

信号：rank(净流入) - rank(总市值)，市值中性化后的主力净流入强度。
正值 = 净流入排名远超市值排名 → 主力积极买入（小盘/中等盘中的大资金行为）。
负值 = 净流入排名远低于市值排名 → 主力相对消极。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div, ts_mean

__alpha_meta__ = {
    "id": "my_main_flow",
    "nickname": "主力资金流 — 市值中性化净流入 rank",
    "theme": ["sentiment", "volume"],
    "formula_latex": "RANK(main_net_flow) - RANK(mcap)",
    "columns_required": ["fund:main_net_flow", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 1,
    "notes": (
        "rank(净流入) - rank(总市值)。消除市值大小对净流入绝对值的偏向。"
        "数据来源：问财主力资金净流入、总市值。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    # rank(净流入) - rank(市值) → 市值中性化后的净流入排名
    return rank(flow) - rank(mcap)

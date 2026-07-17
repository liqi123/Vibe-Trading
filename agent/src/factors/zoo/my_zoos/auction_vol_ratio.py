"""竞价量异常因子

信号：当日集合竞价成交量 / 5日均量。
比值 > 1 = 竞价放量（可能预示当日活跃），
比值 < 1 = 竞价缩量。
Cross-sectional rank 归一化。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_auction_vol_ratio",
    "nickname": "竞价量异常 — 集合竞价量 / 5日均量",
    "theme": ["volume", "microstructure"],
    "formula_latex": "RANK(auction_vol / MA5(auction_vol))",
    "columns_required": ["fund:auction_vol_ratio"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 5,
    "notes": (
        "集合竞价成交量相对于过去5日均量的比值。"
        "竞价放量说明开盘前就有大量资金参与，"
        "可能是当日趋势的信号。"
        "数据来自本地 auction 表。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return rank(panel["fund:auction_vol_ratio"])

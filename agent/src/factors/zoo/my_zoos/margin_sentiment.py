"""融资余额变化因子（改进版）

信号：融资余额日变化率，2日均线平滑后 rank。
- 融资余额日变化率（已有字段 fund:margin_change）
- 2日均线平滑去除噪声
- 正值 = 加杠杆（看多），负值 = 去杠杆（看空）
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "my_margin_sentiment",
    "nickname": "融资情绪 — Δ余额% × 2日均线",
    "theme": ["sentiment"],
    "formula_latex": "RANK(TS_MEAN(margin_change, 2))",
    "columns_required": ["fund:margin_change"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 2,
    "notes": (
        "融资余额日变化率 × 2日均线平滑后 rank。"
        "数据来源：问财融资余额。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return rank(ts_mean(panel["fund:margin_change"], 2))

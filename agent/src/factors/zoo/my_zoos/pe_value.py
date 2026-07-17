"""市盈率价值因子（改进版）

信号：E/P + B/P 复合价值评分。
- E/P = 1/PE_TTM（过滤 PE≤0）
- B/P = 1/PB（过滤 PB≤0）
- 对每只股票算全市场 z-score 后等权相加
- 分数越高 = 价值越被低估

参考：Fama-French HML，Asness (2015) 跨资产价值因子。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import zscore

__alpha_meta__ = {
    "id": "my_pe_value",
    "nickname": "价值复合 — E/P + B/P z-score",
    "theme": ["value"],
    "formula_latex": "Z(1/PE_TTM) + Z(1/PB)",
    "columns_required": ["fund:pe_ttm", "fund:pb"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 1,
    "notes": (
        "E/P + B/P 复合价值评分。过滤亏损股和负净资产。"
        "数据来源：问财市盈率ttm、市净率。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pe = panel["fund:pe_ttm"]
    pb = panel["fund:pb"]
    ep = 1.0 / pe.where(pe > 0)
    bp = 1.0 / pb.where(pb > 0)
    return zscore(ep) + zscore(bp)

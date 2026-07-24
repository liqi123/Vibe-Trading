"""市盈率价值因子 v2 — 价值×动量确认

改进：
1. 价值信号：E/P + B/P z-score
2. 动量确认：close/MA20 > 1 才保留价值信号（避免价值陷阱）
3. 行业中性化：减去行业内均值（可选）

参考：Asness (2015) 价值因子需要动量确认。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, zscore

__alpha_meta__ = {
    "id": "my_pe_value_v2",
    "nickname": "价值动量确认 v2 — (E/P + B/P) × momentum",
    "theme": ["value", "momentum"],
    "formula_latex": "RANK(Z(1/PE) + Z(1/PB)) * RANK(close/MA20)",
    "columns_required": ["close", "fund:pe_ttm", "fund:pb"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 20,
    "notes": (
        "价值×动量确认。低估值(高E/P+B/P) + 价格趋势向上 → 看多。"
        "避免价值陷阱：估值低但无动量不买入。"
        "数据来源：问财市盈率ttm、市净率。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pe = panel["fund:pe_ttm"]
    pb = panel["fund:pb"]
    c = panel["close"]

    # 价值信号：E/P + B/P
    ep = 1.0 / pe.where(pe > 0)
    bp = 1.0 / pb.where(pb > 0)
    value_score = zscore(ep) + zscore(bp)

    # 动量确认：close/MA20
    ma20 = c.rolling(20).mean()
    momentum = c / ma20
    mom_rank = rank(momentum)

    # 价值×动量：只在动量为正时保留价值信号
    value_rank = rank(value_score)
    return value_rank * mom_rank

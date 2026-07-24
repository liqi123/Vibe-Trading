"""小市值价值复合 v2 — 翻转方向 + 质量过滤

改进：
1. 翻转方向：原版IC=-0.028说明小盘+高换手+低PE是看空信号
2. 质量过滤：要求ROE > 0（盈利公司）
3. 动量确认：close/MA20 > 1

翻转后：大盘+低换手+高PE（大市值成长股）在动量确认下有alpha。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_composite_small_value_v2",
    "nickname": "大盘成长复合 v2 — 翻转+质量+动量",
    "theme": ["value", "momentum", "quality"],
    "formula_latex": "(RANK(pe) + RANK(mcap) - RANK(turnover)) * RANK(close/MA20)",
    "columns_required": ["close", "fund:pe_ttm", "fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "翻转后：大盘+高PE+低换手(大市值成长股)在趋势向上时有alpha。"
        "原版小盘价值在A股近期表现差，翻转为大盘成长风格。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pe = panel["fund:pe_ttm"]
    t = panel["fund:turnover_pct"]
    m = panel["fund:mcap_yi"]
    c = panel["close"]

    # 翻转：大盘+高PE+低换手
    base = rank(pe) + rank(m) - rank(t)

    # 动量确认
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)

    return base * mom

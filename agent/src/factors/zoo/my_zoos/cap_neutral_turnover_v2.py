"""市值中性换手率 v2 — 翻转方向 + 动量过滤

改进：
1. 翻转方向：rank(mcap) - rank(turnover)（原版IC为负）
2. 动量过滤：只在close/MA20 > 1时保留信号

原始IC=-0.025说明：高换手+小盘实际是看空信号。
翻转后：低换手+大盘（冷门大票）反而有正向预测力。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_cap_neutral_turnover_v2",
    "nickname": "市值中性换手率 v2 — 翻转+动量",
    "theme": ["volume", "microstructure"],
    "formula_latex": "(RANK(mcap) - RANK(turnover)) * RANK(close/MA20)",
    "columns_required": ["close", "fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "翻转动量：低换手+大盘(冷门大票)在趋势向上时有正向alpha。"
        "原版IC为负说明方向反了。加动量过滤避免震荡市。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    t = panel["fund:turnover_pct"]
    m = panel["fund:mcap_yi"]
    c = panel["close"]

    # 翻转方向：大盘低换手 > 小盘高换手
    base = rank(m) - rank(t)

    # 动量过滤
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)

    return base * mom

from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_composite_small_value",
    "nickname": "小市值价值复合 — rank(-PE) + rank(turnover) - rank(mcap)",
    "theme": ["value", "microstructure"],
    "formula_latex": "RANK(-pe_ttm) + RANK(turnover_pct) - RANK(mcap_yi)",
    "columns_required": ["fund:pe_ttm", "fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "全截面合成：低估值 + 高换手 + 小市值。经典A股小市值反转风格。"
        "无滚动窗口，无NaN传播风险。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return rank(-panel["fund:pe_ttm"]) + rank(panel["fund:turnover_pct"]) - rank(panel["fund:mcap_yi"])

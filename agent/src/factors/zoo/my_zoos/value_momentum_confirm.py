from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_value_momentum_confirm",
    "nickname": "估值动量确认 — rank(-PE) × rank(close/MA20)",
    "theme": ["value", "momentum"],
    "formula_latex": "RANK(-pe_ttm) * RANK(close / MA(close, 20))",
    "columns_required": ["close", "fund:pe_ttm"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "低估值(高-rank(-PE)) + 价格趋势向上 → 看多。"
        "高估值 + 价格下跌 → 看空。避免价值陷阱：估值低但无动量不买入。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    pe = panel["fund:pe_ttm"]
    value_score = rank(-pe)
    mom_score = rank(c / c.rolling(20).mean())
    return value_score * mom_score

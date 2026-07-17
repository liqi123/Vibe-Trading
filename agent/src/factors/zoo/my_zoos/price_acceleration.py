from __future__ import annotations

import pandas as pd

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_price_acceleration",
    "nickname": "价格加速度 — rank(Δ5(close / MA5))",
    "theme": ["momentum"],
    "formula_latex": "RANK(DELTA(close / MA(close, 5), 5))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 10,
    "notes": (
        "价格相对于5日均线偏离度的5日变化。正值=价格加速上涨；"
        "负值=价格加速下跌。捕捉趋势动能变化。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    rel = c / c.rolling(5).mean()
    accel = delta(rel, 5)
    return rank(accel)

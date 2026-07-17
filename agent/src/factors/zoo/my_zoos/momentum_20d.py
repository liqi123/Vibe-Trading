from __future__ import annotations

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_momentum_20d",
    "nickname": "20日纯动量 — rank(delta(close, 20))",
    "theme": ["momentum"],
    "formula_latex": "RANK(DELTA(close, 20))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": "GTJA #106 简化版。20日纯价格动量。正IC=动量，负IC=反转。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return rank(delta(panel["close"], 20))

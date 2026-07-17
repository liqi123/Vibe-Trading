from __future__ import annotations

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_momentum_5d",
    "nickname": "5日纯动量 — rank(delta(close, 5))",
    "theme": ["momentum"],
    "formula_latex": "RANK(DELTA(close, 5))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": "GTJA #014. 纯价格动量: 5日涨幅排名。正IC=动量效应，负IC=反转效应。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return rank(delta(panel["close"], 5))

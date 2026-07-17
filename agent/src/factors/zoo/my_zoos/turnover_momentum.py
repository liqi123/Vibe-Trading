from __future__ import annotations

import pandas as pd

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_turnover_momentum",
    "nickname": "换手动量 — rank(Δclose(7)) × -rank(turnover/MA20)",
    "theme": ["momentum", "volume"],
    "formula_latex": "RANK(DELTA(close, 7)) * -1 * RANK(turnover_pct / MA(turnover_pct, 20))",
    "columns_required": ["close", "fund:turnover_pct"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "GTJA #025 简化版。价格7日动量 × 换手率20日相对强度(取负)。"
        "上涨+缩量→正值(筹码锁定看好)；上涨+放量→负值(获利了结)；"
        "下跌+放量→正值(恐慌释放完毕)；下跌+缩量→负值(阴跌无人问津)。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    t = panel["fund:turnover_pct"]
    mom = delta(c, 7)
    turnover_ratio = t / t.rolling(20).mean()
    return rank(mom) * (-1.0 * rank(turnover_ratio))

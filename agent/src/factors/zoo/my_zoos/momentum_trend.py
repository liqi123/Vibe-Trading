from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_momentum_trend",
    "nickname": "趋势加速度 — rank(close/MA20) - rank(close/MA60)",
    "theme": ["momentum"],
    "formula_latex": "RANK(close / MA(close, 20)) - RANK(close / MA(close, 60))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 60,
    "min_warmup_bars": 61,
    "notes": (
        "短期动量(20日) - 长期动量(60日)。正值=短期跑赢长期(上升加速)；"
        "负值=短期跑输长期(上升减速/下降加速)。趋势跟踪因子。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    mom_short = c / c.rolling(20).mean()
    mom_long = c / c.rolling(60).mean()
    return rank(mom_short) - rank(mom_long)

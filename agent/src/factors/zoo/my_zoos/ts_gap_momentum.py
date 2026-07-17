from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_ts_gap_momentum",
    "nickname": "缺口动量 — rank(open/prev_close - 1)",
    "theme": ["momentum", "microstructure"],
    "formula_latex": "RANK(open / delay(close,1) - 1)",
    "columns_required": ["open", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 2,
    "notes": "时序因子。隔夜缺口大小取正。跳空高开→继续涨; 跳空低开→继续跌。A股缺口动量效应(非回补)。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"].astype(float)
    c = panel["close"].astype(float)
    gap = o / c.shift(1) - 1
    return rank(gap)

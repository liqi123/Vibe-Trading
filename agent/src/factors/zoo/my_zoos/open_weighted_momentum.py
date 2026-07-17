from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_open_weighted_momentum",
    "nickname": "开盘加权动量 — -rank(sign(Δ(open*0.85+high*0.15, 4)))",
    "theme": ["reversal"],
    "formula_latex": "-1 * RANK(SIGN(DELTA(open*0.85 + high*0.15, 4)))",
    "columns_required": ["open", "high"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 4,
    "min_warmup_bars": 5,
    "notes": "GTJA #006. 开盘加权价(85%open+15%high)的4日变化方向取反。趋势末端反转信号。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"]
    h = panel["high"]
    weighted = o * 0.85 + h * 0.15
    chg = delta(weighted, 4)
    sign = np.sign(chg)
    return -1.0 * rank(sign)

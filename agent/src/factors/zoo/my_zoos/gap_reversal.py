from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_gap_reversal",
    "nickname": "跳空反转 — -rank((open - prev_close) / prev_close)",
    "theme": ["reversal"],
    "formula_latex": "-1 * RANK((open - delay(close, 1)) / delay(close, 1))",
    "columns_required": ["close", "open"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 2,
    "notes": (
        "跳空幅度取负。大幅高开→看空(回补)；大幅低开→看多(回补)。"
        "A股跳空回补效应，简单有效。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    o = panel["open"]
    prev_c = c.shift(1)
    gap = (o - prev_c) / prev_c.replace(0, np.nan)
    return -1.0 * rank(gap)

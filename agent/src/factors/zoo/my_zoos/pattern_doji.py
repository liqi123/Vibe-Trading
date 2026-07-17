from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_pattern_doji",
    "nickname": "十字星 — rank(-|c-o|/(h-l)) × sign(prior_trend)",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK(-|close-open|/(high-low)) * SIGN(close-delay(close,1))",
    "columns_required": ["open", "high", "low", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 2,
    "min_warmup_bars": 5,
    "notes": "K线形态。十字星(开盘=收盘)表示多空平衡。前一日上涨后出现十字星→趋势可能终结。值高=上涨趋势末端的十字星→看空。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    rng = (h - l).replace(0, np.nan)
    body_ratio = (c - o).abs() / rng
    doji = -body_ratio
    prior_trend = (c - c.shift(1))
    return rank(doji) * prior_trend

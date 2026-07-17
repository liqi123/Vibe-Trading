from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_corr

__alpha_meta__ = {
    "id": "my_high_volume_corr",
    "nickname": "高价量相关 — -corr(high, rank(volume), 5)",
    "theme": ["volume"],
    "formula_latex": "-1 * CORR(high, RANK(volume), 5)",
    "columns_required": ["high", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 10,
    "notes": (
        "GTJA #062 移植。高点和成交量排名的5日相关系数取负。"
        "高价+放量(正相关)→看空；高价+缩量(负相关)→看多。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"]
    v = panel["volume"]
    return -1.0 * ts_corr(h, rank(v), 5)

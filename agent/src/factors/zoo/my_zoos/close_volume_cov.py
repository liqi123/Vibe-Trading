from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_cov

__alpha_meta__ = {
    "id": "my_close_volume_cov",
    "nickname": "收盘量价协方差 — -rank(cov(rank(close), rank(volume), 5))",
    "theme": ["volume"],
    "formula_latex": "-1 * RANK(COV(RANK(close), RANK(volume), 5))",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 10,
    "notes": (
        "GTJA #099 移植。收盘价和成交量的排名协方差，5日窗口。"
        "衡量收盘与量排名联动的稳定性。协方差高(正)→因子负→看空。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    cov = ts_cov(rank(c), rank(v), 5)
    return -1.0 * rank(cov)

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_corr, ts_std

__alpha_meta__ = {
    "id": "my_volume_volatility",
    "nickname": "量波动率价 — -std(vol,10) × corr(close, vol, 5)",
    "theme": ["volume", "volatility"],
    "formula_latex": "-1 * TS_STD(volume, 10) * TS_CORR(close, volume, 5)",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 10,
    "min_warmup_bars": 15,
    "notes": (
        "GTJA #042 简化版。成交量10日波动率 × 收盘价与量5日相关系数，取负。"
        "高量波动+量价正相关(放量上涨末端)→看空；高量波动+负相关(放量下跌末端)→看多。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    v_std = ts_std(v, 10)
    cv_corr = ts_corr(c, v, 5)
    return -1.0 * v_std * cv_corr

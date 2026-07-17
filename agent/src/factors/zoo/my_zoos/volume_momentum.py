from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_volume_momentum",
    "nickname": "量价动量组合 — rank(vol/MA5) × rank(close/MA20)",
    "theme": ["momentum", "volume"],
    "formula_latex": "RANK(volume/MA5) * RANK(close/MA20)",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 20,
    "min_warmup_bars": 21,
    "notes": (
        "GTJA #033 简化版。成交量5日相对强度 × 价格20日相对强度。"
        "正=放量+上涨趋势确认；负=缩量+下跌趋势/放量+下跌(分歧)。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    vol_ratio = v / v.rolling(5).mean()
    price_ratio = c / c.rolling(20).mean()
    return rank(vol_ratio) * rank(price_ratio)

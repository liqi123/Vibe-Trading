from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_flow_volume_surge",
    "nickname": "主力放量确认 — rank(flow/amount) × rank(vol/MA5)",
    "theme": ["sentiment", "volume"],
    "formula_latex": "RANK(main_net_flow / amount) * RANK(volume / MA(volume, 5))",
    "columns_required": ["fund:main_net_flow", "amount", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "主力净流入占成交额比(截面) × 成交量5日相对强度(OHLCV无NaN)。"
        "正值=主力买入+放量(真突破信号)；负值=主力卖出/假突破。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    amount = panel["amount"]
    v = panel["volume"]
    flow_ratio = flow / amount.replace(0, np.nan)
    vol_surge = v / v.rolling(5).mean()
    return rank(flow_ratio) * rank(vol_surge)

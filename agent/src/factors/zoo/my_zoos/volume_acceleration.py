from __future__ import annotations

import pandas as pd

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_volume_acceleration",
    "nickname": "量加速度 — rank(Δ(vol/MA5, 5))",
    "theme": ["volume"],
    "formula_latex": "RANK(DELTA(volume / MA(volume, 5), 5))",
    "columns_required": ["volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 10,
    "notes": (
        "成交量相对5日均量的5日变化。正值=成交量加速放量(情绪亢奋末端)；"
        "负值=成交量加速缩量(冷清底部)。差异化的量能因子。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    v = panel["volume"]
    vol_ratio = v / v.rolling(5).mean()
    accel = delta(vol_ratio, 5)
    return rank(accel)

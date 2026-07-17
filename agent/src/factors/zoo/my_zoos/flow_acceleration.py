from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_flow_acceleration",
    "nickname": "资金加速度 — rank(Δ5(flow/mcap))",
    "theme": ["sentiment", "momentum"],
    "formula_latex": "RANK(DELTA(main_net_flow / mcap, 5))",
    "columns_required": ["fund:main_net_flow", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "主力资金强度(净流入/市值)的5日变化。正值=主力资金加速流入；负值=加速流出。"
        "捕捉主力资金趋势变化，比单日净流入更稳定。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    intensity = flow / mcap.replace(0, np.nan)
    accel = delta(intensity, 5)
    return rank(accel)

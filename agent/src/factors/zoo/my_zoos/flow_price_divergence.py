from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_cov

__alpha_meta__ = {
    "id": "my_flow_price_divergence",
    "nickname": "资金流价背离 — -rank(cov(rank(flow/mcap), rank(close), 5))",
    "theme": ["sentiment", "volume"],
    "formula_latex": "-1 * RANK(COV(RANK(main_net_flow / mcap), RANK(close), 5))",
    "columns_required": ["close", "fund:main_net_flow", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 10,
    "notes": (
        "GTJA #099 逻辑移植到主力资金。将主力资金强度(净流入/市值)与收盘价的排名协方差取负。"
        "主力持续买入+价格上涨(协方差正)→看空(透支)；主力买入+价格不动→看多(潜伏)。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    flow_intensity = flow / mcap.replace(0, np.nan)
    cov = ts_cov(rank(flow_intensity), rank(c), 5)
    return -1.0 * rank(cov)

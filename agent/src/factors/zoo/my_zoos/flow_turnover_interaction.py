from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_flow_turnover_interaction",
    "nickname": "资金换手交互 — rank(flow/mcap) × rank(turnover)",
    "theme": ["sentiment", "volume"],
    "formula_latex": "RANK(main_net_flow / mcap_yi) * RANK(turnover_pct)",
    "columns_required": ["fund:main_net_flow", "fund:mcap_yi", "fund:turnover_pct"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "全截面，无滚动窗口。主力资金强度(净流入/市值) × 换手率。"
        "高值=主力大举买入+交投活跃(强做多信号)；低值=主力卖出+冷清。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    t = panel["fund:turnover_pct"]
    flow_intensity = flow / mcap.replace(0, np.nan)
    return rank(flow_intensity) * rank(t)

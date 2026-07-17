from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_cap_neutral_turnover",
    "nickname": "市值中性换手率 — rank(turnover) - rank(mcap)",
    "theme": ["volume", "microstructure"],
    "formula_latex": "RANK(turnover_pct) - RANK(mcap_yi)",
    "columns_required": ["fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "全截面 rank，无滚动窗口。换手率排名减去市值排名。"
        "正值=小盘高换手(活跃小票)，负值=大盘低换手(冷门大票)。"
        "纯截面操作，无NaN传播风险。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    t = panel["fund:turnover_pct"]
    m = panel["fund:mcap_yi"]
    return rank(t) - rank(m)

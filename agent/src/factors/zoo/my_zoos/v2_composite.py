"""V2复合因子 — 多信号等权组合

组合已验证的v2因子：
1. 市值中性换手率v2 (IC=0.031)
2. 大盘成长复合v2 (IC=0.027)
3. 资金换手交互v2 (IC=0.022)
4. 主力资金流v2 (IC=0.015)

等权复合，利用因子间低相关性提高稳定性。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_v2_composite",
    "nickname": "V2复合因子 — 4因子等权",
    "theme": ["composite"],
    "formula_latex": "(RANK(cap_turnover_v2) + RANK(small_value_v2) + RANK(flow_turnover_v2) + RANK(main_flow_v2)) / 4",
    "columns_required": ["close", "volume", "fund:turnover_pct", "fund:mcap_yi", "fund:pe_ttm", "fund:main_net_flow"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "组合4个v2因子：市值中性换手、大盘成长、资金换手交互、主力资金流。"
        "等权复合，利用因子间低相关性提高稳定性。"
    ),
}


def _cap_neutral_turnover_v2(panel):
    t = panel["fund:turnover_pct"]
    m = panel["fund:mcap_yi"]
    c = panel["close"]
    base = rank(m) - rank(t)
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)
    return base * mom


def _small_value_v2(panel):
    pe = panel["fund:pe_ttm"]
    t = panel["fund:turnover_pct"]
    m = panel["fund:mcap_yi"]
    c = panel["close"]
    base = rank(pe) + rank(m) - rank(t)
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)
    return base * mom


def _flow_turnover_v2(panel):
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    c = panel["close"]
    import numpy as np
    flow_intensity = flow / mcap.replace(0, pd.NA)
    base = rank(mcap) - rank(flow_intensity)
    ma20 = c.rolling(20).mean()
    mom = rank(c / ma20)
    return base * mom


def _main_flow_v2(panel):
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    v = panel["volume"]
    base = rank(mcap) - rank(flow)
    vol_surge = rank(v / v.rolling(5).mean())
    return base * vol_surge


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    f1 = _cap_neutral_turnover_v2(panel)
    f2 = _small_value_v2(panel)
    f3 = _flow_turnover_v2(panel)
    f4 = _main_flow_v2(panel)
    return (rank(f1) + rank(f2) + rank(f3) + rank(f4)) / 4

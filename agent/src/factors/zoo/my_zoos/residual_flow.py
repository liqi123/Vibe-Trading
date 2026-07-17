from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_residual_flow",
    "nickname": "残差资金流强度 — residual(main_net_flow/amount | ret)",
    "theme": ["sentiment", "liquidity"],
    "formula_latex": "RANK(RESIDUAL(main_net_flow / amount, ret, cs))",
    "columns_required": ["close", "amount", "fund:main_net_flow"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "残差资金流强度因子。"
        "传统资金流强度 = main_net_flow / amount 与当日涨跌幅高度相关，"
        "截面回归剥离涨跌幅影响后，残差代表剔除价格噪音后的'真实'资金流信号。"
        "大单残差资金流强度 IC=0.054 IR=3.96 (开源证券2020.05)。"
        "用 fund:main_net_flow 作为大单净流入的 proxy。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    flow = panel["fund:main_net_flow"].astype(float)
    amt = panel.get("amount")
    if amt is None:
        amt = c * panel.get("volume", pd.DataFrame(0, index=c.index, columns=c.columns)).astype(float)

    ret = c.pct_change()
    flow_intensity = flow / (amt + 1e-12)

    result = flow_intensity * 0.0

    for t in range(len(flow_intensity)):
        row = flow_intensity.iloc[t]
        ret_row = ret.iloc[t]
        mask = row.notna() & ret_row.notna() & np.isfinite(row.values) & np.isfinite(ret_row.values)
        vals = row.values[mask.values]
        ret_vals = ret_row.values[mask.values]
        n = len(vals)
        if n < 30:
            continue
        # OLS: flow_intensity = alpha + beta * ret + epsilon
        A = np.column_stack([ret_vals, np.ones(n)])
        try:
            beta, alpha = np.linalg.lstsq(A, vals, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        residual = pd.Series(np.nan, index=row.index)
        residual[mask] = vals - (beta * ret_vals + alpha)
        result.iloc[t] = residual

    return rank(result)

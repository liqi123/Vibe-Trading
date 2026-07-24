"""主力资金流 v3 — 回归去噪版

借鉴 residual_flow 的成功经验，用回归方法去除噪音：
1. 资金流/成交额 与 涨跌幅 的截面回归
2. 残差 = 剔除价格影响后的"纯"资金流信号
3. 残差越大 = 资金流入异常（可能是主力吸筹）

这与 residual_flow 类似，但使用不同的归一化方式。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_main_flow_v3",
    "nickname": "主力资金流 v3 — 回归去噪",
    "theme": ["sentiment", "volume"],
    "formula_latex": "RANK(RESIDUAL(flow/amount, ret, cs))",
    "columns_required": ["close", "amount", "fund:main_net_flow"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "回归去噪：资金流/成交额 与涨跌幅截面回归，残差=异常资金流。"
        "与residual_flow类似但使用不同的归一化方式。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"].astype(float)
    c = panel["close"].astype(float)
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
        A = np.column_stack([ret_vals, np.ones(n)])
        try:
            beta, alpha = np.linalg.lstsq(A, vals, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue
        residual = pd.Series(np.nan, index=row.index)
        residual[mask] = vals - (beta * ret_vals + alpha)
        result.iloc[t] = residual

    return rank(result)

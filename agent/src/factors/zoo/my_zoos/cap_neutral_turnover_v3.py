"""市值中性换手率 v3 — 回归去噪版

借鉴 residual_flow 的成功经验，用回归方法去除噪音：
1. 换手率/市值 与 涨跌幅 的截面回归
2. 残差 = 剔除价格影响后的"纯"换手率信号
3. 残差越大 = 换手率异常高（可能是主力动作）

参考：残差资金流因子 IC=0.018, IR=0.29 的成功经验。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_cap_neutral_turnover_v3",
    "nickname": "市值中性换手率 v3 — 回归去噪",
    "theme": ["volume", "microstructure"],
    "formula_latex": "RANK(RESIDUAL(turnover/mcap, ret, cs))",
    "columns_required": ["close", "fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "回归去噪：换手率/市值 与涨跌幅截面回归，残差=异常换手率。"
        "借鉴残差资金流因子的成功经验。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    turnover = panel["fund:turnover_pct"].astype(float)
    mcap = panel["fund:mcap_yi"].astype(float)
    c = panel["close"].astype(float)

    ret = c.pct_change()
    intensity = turnover / mcap.replace(0, pd.NA)

    result = intensity * 0.0

    for t in range(len(intensity)):
        row = intensity.iloc[t]
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

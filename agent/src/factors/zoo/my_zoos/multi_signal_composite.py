"""多信号复合因子 — 综合资金流+换手率+动量

策略：
1. 残差资金流（已验证有效）
2. 残差换手率（v3版本）
3. 动量确认（close/MA20）
4. 等权复合

参考：多因子复合可以提高稳定性和降低波动。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_multi_signal_composite",
    "nickname": "多信号复合 — 残差资金流+残差换手+动量",
    "theme": ["sentiment", "volume", "momentum"],
    "formula_latex": "(RANK(residual_flow) + RANK(residual_turnover) + RANK(momentum)) / 3",
    "columns_required": ["close", "amount", "volume", "fund:main_net_flow", "fund:turnover_pct", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 20,
    "notes": (
        "多信号复合：残差资金流+残差换手率+动量，等权平均。"
        "利用多个独立信号的互补性提高稳定性。"
    ),
}


def _compute_residual(panel: dict[str, pd.DataFrame], col: str) -> pd.DataFrame:
    """计算残差因子"""
    data = panel[col].astype(float)
    c = panel["close"].astype(float)
    ret = c.pct_change()

    result = data * 0.0

    for t in range(len(data)):
        row = data.iloc[t]
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


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    flow = panel["fund:main_net_flow"].astype(float)
    turnover = panel["fund:turnover_pct"].astype(float)
    mcap = panel["fund:mcap_yi"].astype(float)
    amt = panel.get("amount")
    if amt is None:
        amt = c * panel.get("volume", pd.DataFrame(0, index=c.index, columns=c.columns)).astype(float)

    # 1. 残差资金流
    flow_intensity = flow / (amt + 1e-12)
    residual_flow = _compute_residual_from_series(flow_intensity, c)

    # 2. 残差换手率
    turnover_intensity = turnover / mcap.replace(0, pd.NA)
    residual_turnover = _compute_residual_from_series(turnover_intensity, c)

    # 3. 动量
    ma20 = c.rolling(20).mean()
    momentum = rank(c / ma20)

    # 复合
    return (rank(residual_flow) + rank(residual_turnover) + momentum) / 3


def _compute_residual_from_series(data: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """从DataFrame计算残差"""
    ret = close.pct_change()
    result = data * 0.0

    for t in range(len(data)):
        row = data.iloc[t]
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

    return result

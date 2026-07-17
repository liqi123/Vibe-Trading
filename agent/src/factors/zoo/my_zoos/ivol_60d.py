from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, ts_std, ts_corr

__alpha_meta__ = {
    "id": "my_ivol_60d",
    "nickname": "特质波动率 — -rank(RESVOL_60d)",
    "theme": ["risk", "volatility"],
    "formula_latex": "-1 * RANK(STD(ret) * SQRT(1 - CORR(ret, mkt)^2))",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 61,
    "notes": (
        "特质波动率因子 — 经典A股负向因子。"
        "低特质波动率 = 低残差波动（剥离市场beta后）→ 高预期收益。"
        "计算：60日滚动回归残差波动率 = total_vol * sqrt(1 - r^2)，"
        "其中 r = stock_ret 与 mkt_ret 的60日相关系数。"
        "A股IC约-0.07~-0.10，ICIR约-3~-5（东北证券2025）。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ret = c.pct_change()

    mkt_ret = ret.mean(axis=1)
    mkt_ret_df = mkt_ret.to_frame()
    mkt_ret_df = pd.concat([mkt_ret_df] * ret.shape[1], axis=1)
    mkt_ret_df.columns = ret.columns
    mkt_ret_df.index = ret.index

    stock_vol = ts_std(ret, 60)
    corr = ts_corr(ret, mkt_ret_df, 60)

    residual_vol = stock_vol * np.sqrt(np.maximum(1.0 - corr ** 2, 0.0))

    return -1.0 * rank(residual_vol)

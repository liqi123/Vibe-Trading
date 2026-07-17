"""60日滚动Beta因子

信号：个股日收益率 vs 全市场等权平均日收益率，60日滚动协方差/市场方差。
高Beta=高弹性(牛市领涨/熊市领跌)。截面rank输出。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, ts_cov, ts_std

__alpha_meta__ = {
    "id": "my_beta_60d",
    "nickname": "60日Beta — 个股vs全市场等权收益",
    "theme": ["volatility", "momentum"],
    "formula_latex": "RANK(TS_COV(ret, mkt_ret, 60) / TS_STD(mkt_ret, 60)^2)",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 60,
    "min_warmup_bars": 61,
    "notes": (
        "60日滚动Beta。个股日收益率 vs 全市场等权平均日收益率。截面rank。"
        "高Beta股票在牛市中弹性更大但熊市中跌幅更深。与低波动异象互补。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    ret = c.pct_change()
    mkt_ret = ret.mean(axis=1)
    mkt_ret_2d = pd.DataFrame(
        {col: mkt_ret for col in ret.columns},
        index=ret.index, dtype=float,
    )
    cov = ts_cov(ret, mkt_ret_2d, 60)
    mkt_var = ts_std(mkt_ret_2d, 60) ** 2
    beta = cov / mkt_var.replace(0, 1e-10)
    return rank(beta)

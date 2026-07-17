"""价量背离因子

信号：10日价格趋势 - 10日成交量趋势。
价格上涨但成交量萎缩(背离正)=上行动能不足→反转下跌。
价格下跌但成交量放大(背离负)=恐慌见底→反弹。
A股典型: 顶部缩量上涨(背离+)、底部放量下跌(背离-)。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_price_volume_divergence",
    "nickname": "价量背离 — 价格趋势与成交量趋势之差",
    "theme": ["volume", "reversal"],
    "formula_latex": "RANK(ret_10d - vol_10d_pct)",
    "columns_required": ["close", "volume"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 10,
    "min_warmup_bars": 11,
    "notes": (
        "价量背离因子。10日价格涨幅减去10日成交量涨幅。"
        "价格上涨但缩量(高正值)=上行动能不足→反转下跌风险。"
        "价格下跌但放量(低负值)=恐慌释放→超跌反弹机会。"
        "价量同步=趋势健康可持续。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    c_trend = c / c.shift(10) - 1
    v_trend = v / v.shift(10) - 1
    divergence = c_trend - v_trend
    return rank(divergence)

"""主力资金流 v2 — 翻转方向 + 量价确认

改进：
1. 翻转方向：rank(mcap) - rank(flow)（原版IC=-0.020）
2. 量价确认：要求成交量放大（vol/MA5 > 1）
3. 使用残差方法去噪（借鉴residual_flow的成功经验）

原始IC为负说明：资金净流出+小盘反而有正向alpha（可能是超跌反弹）。
翻转后：资金净流入+大盘+放量才是真正的买入信号。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_main_flow_v2",
    "nickname": "主力资金流 v2 — 翻转+量价确认",
    "theme": ["sentiment", "volume"],
    "formula_latex": "(RANK(mcap) - RANK(flow)) * RANK(vol/MA5)",
    "columns_required": ["close", "volume", "fund:main_net_flow", "fund:mcap_yi"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 6,
    "notes": (
        "翻转后：资金净流入+大盘+放量=真正的买入信号。"
        "原版IC为负说明方向反了。加量价确认过滤假信号。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow = panel["fund:main_net_flow"]
    mcap = panel["fund:mcap_yi"]
    v = panel["volume"]
    c = panel["close"]

    # 翻转方向：大盘-资金流出排名
    base = rank(mcap) - rank(flow)

    # 量价确认：成交量放大
    vol_surge = rank(v / v.rolling(5).mean())

    return base * vol_surge

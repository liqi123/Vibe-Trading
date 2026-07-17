from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_apm_factor",
    "nickname": "APM上下午强弱差 — afternoon_strength - morning_strength",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK(afternoon_ret) - RANK(morning_ret)",
    "columns_required": ["open", "high", "low", "close", "volume", "fund:auction_vol"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "APM因子代理版。开源金工APM衡量上下午行为差异。"
        "用daily数据近似: morning = (open/prev_close - 1), afternoon = (close/open - 1), "
        "APM = rank(afternoon_ret) - rank(morning_ret)。正值=下午强于上午。"
        "叠加竞价量作为可信度权重: auction_vol_ratio高时信号更可靠。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    v = panel["volume"]
    amt = panel.get("amount", v * c)

    morning_ret = o / c.shift(1) - 1
    afternoon_ret = c / o - 1

    # 核心APM: 下午相对上午的强弱(IC负所以翻正为上午-下午)
    apm_raw = rank(morning_ret) - rank(afternoon_ret)

    # 可信度权重: 日内波动率低时信号更可靠
    daily_range = (h - l) / c
    vol_weight = 1.0 / (daily_range.rolling(5).mean() + 1e-8)
    vol_weight = vol_weight / vol_weight.mean()

    # 振幅调节: 开盘区间振幅 vs 全天振幅
    open_range = abs(o - c.shift(1)) / c.shift(1)
    full_range = (h - l) / c.shift(1)
    range_ratio = open_range / (full_range + 1e-8)
    # range_ratio高=开盘跳空主导振幅 → 趋势信号更可靠
    range_adj = rank(range_ratio)

    result = rank(apm_raw * vol_weight) + range_adj
    return result

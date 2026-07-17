"""涨停动量因子

信号：rank((close/open-1) × (close-low)/(high-low))。
涨停质量判断: 高涨幅+高位收盘=强势涨停(封板好)，次日高开延续概率大。
高涨幅+低位收盘=弱势涨停(烂板)，次日回落概率大。A股特有因子。
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "my_limit_up_momentum",
    "nickname": "涨停动量 — 涨停质量与次日延续概率",
    "theme": ["momentum", "microstructure"],
    "formula_latex": "RANK((close/open-1) × (close-low)/(high-low))",
    "columns_required": ["open", "high", "low", "close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "A股涨停动量因子。日内涨幅 × 收盘位置。"
        "强势涨停(高开高走封板): 涨幅≈10% + 收盘≈高点 → 动量延续。"
        "弱势涨停(烂板回封): 涨幅<5% + 收盘远离高点 → 次日回落。"
        "非涨停股: 正常波动+中性收盘 → 信号居中。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)
    c = panel["close"].astype(float)
    gain = safe_div(c - o, o)
    pos = safe_div(c - l, h - l)
    return rank(gain * pos)

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_ideal_amplitude",
    "nickname": "理想振幅 — 低价态振幅 - 高价态振幅",
    "theme": ["reversal", "microstructure"],
    "formula_latex": "RANK(MEAN(amp | close<MA20) - MEAN(amp | close>MA20))",
    "columns_required": ["close", "high", "low"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 40,
    "notes": (
        "理想振幅因子 — 开源金工2026.6。"
        "将交易日按收盘价与MA20的关系分为高价态和低价态，"
        "分别计算两态下滚动振幅均值，取低价态 - 高价态。"
        "买入：低价态振幅大、高价态振幅小 → 振幅在低位放大、高位收敛。"
        "逻辑：低位放量震荡筑底（洗盘），高位窄幅整理蓄势（控盘）→ 趋势延续概率大。"
        "若高价态振幅大 → 高位宽幅震荡出货；低价态振幅小 → 低位窄幅无人问津。"
    ),
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)

    amplitude = (h - l) / c
    ma20 = c.rolling(20).mean()

    high_state = (c > ma20).astype(float)
    low_state = (c < ma20).astype(float)

    high_amp = (amplitude * high_state).rolling(20).sum()
    low_amp = (amplitude * low_state).rolling(20).sum()
    high_cnt = high_state.rolling(20).sum()
    low_cnt = low_state.rolling(20).sum()

    high_amp_mean = high_amp / (high_cnt + 1e-10)
    low_amp_mean = low_amp / (low_cnt + 1e-10)

    factor = low_amp_mean - high_amp_mean
    return rank(factor)

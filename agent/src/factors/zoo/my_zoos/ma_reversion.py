from __future__ import annotations

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "my_ma_reversion",
    "nickname": "均线回归 — rank(MA12/close)",
    "theme": ["reversal"],
    "formula_latex": "RANK(MEAN(close,12)/close)",
    "columns_required": ["close"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 12,
    "min_warmup_bars": 13,
    "notes": "GTJA #034. MA12与收盘价之比。>1=价格低于均线(超卖), <1=价格高于均线(超买)。均值回归信号。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    return rank(ts_mean(c, 12) / c)

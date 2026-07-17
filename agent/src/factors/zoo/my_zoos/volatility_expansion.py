from __future__ import annotations

from src.factors.base import rank

__alpha_meta__ = {
    "id": "my_volatility_expansion",
    "nickname": "波动率扩张 — rank(sma(hl,10,2)/sma(sma(hl,10,2),10,2))",
    "theme": ["volatility"],
    "formula_latex": "RANK(SMA(h-l,10,2)/SMA(SMA(h-l,10,2),10,2))",
    "columns_required": ["high", "low"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 10,
    "min_warmup_bars": 20,
    "notes": "GTJA #109. 当前10日EMA(range)与自身EMA的EMA之比。>1=波动正在扩张, <1=波动正在收缩。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"]
    l = panel["low"]
    hl = h - l
    num = hl.ewm(alpha=0.2, adjust=False).mean()
    den = num.ewm(alpha=0.2, adjust=False).mean()
    return rank(num / den.replace(0, 1e-10))

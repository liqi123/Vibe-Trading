from __future__ import annotations

from src.factors.base import rank, ts_mean

__alpha_meta__ = {
    "id": "my_range_momentum",
    "nickname": "区间动量 — (h-l-sma(h-l,11,2))/sma(h-l,11,2)*100, ranked",
    "theme": ["volatility", "momentum"],
    "formula_latex": "RANK((h-l-SMA(h-l,11,2))/SMA(h-l,11,2)*100)",
    "columns_required": ["high", "low"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 11,
    "min_warmup_bars": 20,
    "notes": "GTJA #188. 日内区间宽度相对11日EMA的偏离。正值=今日区间异常扩大; 负值=区间收窄。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h = panel["high"]
    l = panel["low"]
    hl = h - l
    sma = hl.ewm(alpha=2/11, adjust=False).mean()
    dev = (hl - sma) / sma.replace(0, 1e-10) * 100
    return rank(dev)

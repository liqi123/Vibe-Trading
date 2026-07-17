from __future__ import annotations

from src.factors.base import rank, delta

__alpha_meta__ = {
    "id": "my_candle_position",
    "nickname": "K线位置变化 — -delta(((c-l)-(h-c))/(h-l), 1)",
    "theme": ["microstructure", "reversal"],
    "formula_latex": "-1 * DELTA(((close-low)-(high-close))/(high-low), 1)",
    "columns_required": ["close", "high", "low"],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 2,
    "notes": "GTJA #002. 收盘价在日内区间位置的日变化取负。position>0=收在高位; delta为正=向上移动。取负后: 收盘上移→看空(反转)。",
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"]
    h = panel["high"]
    l = panel["low"]
    rng = h - l
    pos = ((c - l) - (h - c)) / rng.replace(0, 1e-10)
    return -1.0 * delta(pos, 1)

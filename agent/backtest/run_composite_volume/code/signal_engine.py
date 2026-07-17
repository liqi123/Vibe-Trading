"""Composite Volume Signal Engine.

Combines 6 volume-price factors into a single cross-sectional signal:
  1. price_volume_divergence — 价量背离 (10d price trend - 10d volume trend)
  2. close_volume_cov       — -rank(cov(rank(c), rank(v), 5))
  3. high_volume_corr       — -corr(high, rank(volume), 5)
  4. volume_ratio_reversal  — -rank(volume / MA20)
  5. volume_volatility      — -std(vol,10) × corr(c, v, 5)
  6. ts_gap_momentum        — rank(open / prev_close - 1)

Usage: python -m backtest.runner backtest/run_composite_volume
"""
from __future__ import annotations

import pandas as pd
import numpy as np


class SignalEngine:
    """Cross-sectional composite volume signal engine."""

    def __init__(
        self,
        top_pct: float = 0.2,
        bottom_pct: float = 0.2,
    ) -> None:
        self.top_pct = top_pct
        self.bottom_pct = bottom_pct

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """Generate composite volume signals.

        Args:
            data_map: symbol -> OHLCV DataFrame with columns
                      [open, high, low, close, volume] indexed by date.

        Returns:
            symbol -> pd.Series of target positions in [-1, 1].
        """
        # Build wide panel from data_map
        symbols = sorted(data_map)
        dates = sorted({d for df in data_map.values() for d in df.index})
        if not dates or not symbols:
            return {}

        panel: dict[str, pd.DataFrame] = {}
        for col in ("open", "high", "low", "close", "volume"):
            panel[col] = pd.DataFrame(
                {sym: data_map[sym][col] for sym in symbols},
                index=dates, dtype=float,
            )

        # 1. price_volume_divergence
        c = panel["close"]
        v = panel["volume"]
        f1 = (c / c.shift(10) - 1) - (v / v.shift(10) - 1)
        f1 = f1.rank(axis=1, pct=True)

        # 2. close_volume_cov
        c_rank = c.rank(axis=1, pct=True)
        v_rank = v.rank(axis=1, pct=True)
        f2 = -c_rank.rolling(5, min_periods=5).corr(v_rank)
        f2 = f2.rank(axis=1, pct=True)

        # 3. high_volume_corr
        h = panel["high"]
        v_rank2 = v.rank(axis=1, pct=True)
        f3 = -h.rolling(5, min_periods=5).corr(v_rank2)
        f3 = f3.rank(axis=1, pct=True)

        # 4. volume_ratio_reversal
        f4 = -v / v.rolling(20).mean()
        f4 = f4.rank(axis=1, pct=True)

        # 5. volume_volatility
        v_std = v.rolling(10, min_periods=10).std()
        cv_corr = c.rolling(5, min_periods=5).corr(v)
        f5 = -v_std * cv_corr
        f5 = f5.rank(axis=1, pct=True)

        # 6. ts_gap_momentum
        o = panel["open"]
        f6 = o / c.shift(1) - 1
        f6 = f6.rank(axis=1, pct=True)

        # Equal-weight composite
        composite = (f1 + f2 + f3 + f4 + f5 + f6) / 6.0

        # Cross-sectional signals: top_pct → +1, bottom_pct → -1
        signal_arrays: dict[str, list[tuple]] = {sym: [] for sym in symbols}
        for date in composite.index:
            row = composite.loc[date].dropna()
            if len(row) < 10:
                continue
            pct = row.rank(pct=True)
            for sym in symbols:
                if sym not in pct.index or pd.isna(pct[sym]):
                    continue
                val = pct[sym]
                if val >= 1.0 - self.top_pct:
                    signal = 1.0
                elif val <= self.bottom_pct:
                    signal = -1.0
                else:
                    signal = 0.0
                signal_arrays[sym].append((date, signal))

        signals = {
            sym: pd.Series(
                {d: s for d, s in pairs},
                index=pd.DatetimeIndex(sorted(d for d, _ in pairs)),
            )
            for sym, pairs in signal_arrays.items()
            if pairs
        }
        return signals

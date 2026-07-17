"""Composite Volume Signal Engine — Top 3% long only.

Buy the top 3% of stocks ranked by composite volume factor score.
Equal-weight, daily rebalance. Designed for A-share long-only.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


class SignalEngine:
    """Top 3% composite volume signal."""

    TOP_PCT = 0.03  # buy top 3%

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
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

        c, v, h, o = panel["close"], panel["volume"], panel["high"], panel["open"]

        c_r = c.rank(axis=1, pct=True)
        v_r = v.rank(axis=1, pct=True)
        f1 = (c / c.shift(10) - 1) - (v / v.shift(10) - 1)
        f1 = f1.rank(axis=1, pct=True)
        f2 = -c_r.rolling(5, min_periods=5).corr(v_r)
        f2 = f2.rank(axis=1, pct=True)
        f3 = -h.rolling(5, min_periods=5).corr(v_r)
        f3 = f3.rank(axis=1, pct=True)
        f4 = -(v / v.rolling(20).mean())
        f4 = f4.rank(axis=1, pct=True)
        f5 = -(v.rolling(10, min_periods=10).std() * c.rolling(5, min_periods=5).corr(v))
        f5 = f5.rank(axis=1, pct=True)
        f6 = (o / c.shift(1) - 1)
        f6 = f6.rank(axis=1, pct=True)
        composite = (f1 + f2 + f3 + f4 + f5 + f6) / 6.0

        signals: dict[str, pd.Series] = {}
        threshold = 1.0 - self.TOP_PCT
        signal_arrays: dict[str, list[tuple]] = {sym: [] for sym in symbols}
        for date in composite.index:
            row = composite.loc[date].dropna()
            if len(row) < 20:
                continue
            pct = row.rank(pct=True)
            for sym in symbols:
                if sym not in pct.index or pd.isna(pct[sym]):
                    continue
                if pct[sym] >= threshold:
                    signal_arrays[sym].append((date, 1.0))
                else:
                    signal_arrays[sym].append((date, 0.0))

        signals = {
            sym: pd.Series(
                {d: s for d, s in pairs},
                index=pd.DatetimeIndex(sorted(d for d, _ in pairs)),
            )
            for sym, pairs in signal_arrays.items()
            if pairs
        }
        return signals

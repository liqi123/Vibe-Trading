"""16-Factor Composite Signal Engine — 量价+资金流融合

14-Factor量价因子 + 2个资金流因子：
  f15 主力资金流v2     IC=0.037  IR=0.34  t=5.89
  f16 资金换手交互v2   IC=0.027  IR=0.21  t=3.58

Usage: python -m backtest.runner backtest/run_composite_16factor
"""
from __future__ import annotations

import pandas as pd
import numpy as np


class SignalEngine:
    """16-factor composite signal engine (量价 + 资金流)."""

    def __init__(
        self,
        top_pct: float = 0.2,
        bottom_pct: float = 0.2,
    ) -> None:
        self.top_pct = top_pct
        self.bottom_pct = bottom_pct

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """Generate 16-factor composite signals.

        Args:
            data_map: symbol -> OHLCV DataFrame with columns
                      [open, high, low, close, volume] indexed by date.
                      Optional: main_net_flow, mcap_yi, turnover_pct

        Returns:
            symbol -> pd.Series of target positions in [-1, 1].
        """
        symbols = sorted(data_map)
        dates = sorted({d for df in data_map.values() for d in df.index})
        if not dates or not symbols:
            return {}

        # Build wide panel
        panel: dict[str, pd.DataFrame] = {}
        for col in ("open", "high", "low", "close", "volume"):
            panel[col] = pd.DataFrame(
                {sym: data_map[sym][col] for sym in symbols},
                index=dates, dtype=float,
            )

        # Optional fund data
        for col in ("main_net_flow", "mcap_yi", "turnover_pct"):
            available = all(col in data_map[sym].columns for sym in symbols if col in data_map[sym].columns)
            if available:
                panel[col] = pd.DataFrame(
                    {sym: data_map[sym][col] for sym in symbols if col in data_map[sym].columns},
                    index=dates, dtype=float,
                )

        c = panel["close"]
        v = panel["volume"]
        o = panel["open"]
        h = panel["high"]
        l = panel["low"]

        c_r = c.rank(axis=1, pct=True)
        v_r = v.rank(axis=1, pct=True)

        # ── 14 量价因子 ──

        # f1: 价量10日背离
        f1 = (c / c.shift(10) - 1 - (v / v.shift(10) - 1)).rank(axis=1, pct=True)

        # f2: 价量5日相关性(负)
        f2 = (-c_r.rolling(5, min_periods=5).corr(v_r)).rank(axis=1, pct=True)

        # f3: 高位价量corr(负)
        f3 = (-h.rolling(5, min_periods=5).corr(v_r)).rank(axis=1, pct=True)

        # f4: 量比(负)
        f4 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

        # f5: 量价波动复合(负)
        f5 = (-(v.rolling(10, min_periods=10).std()
                * c.rolling(5, min_periods=5).corr(v))).rank(axis=1, pct=True)

        # f6: 开盘跳空
        f6 = (o / c.shift(1) - 1).rank(axis=1, pct=True)

        # f7: 上影线稳定性(负)
        us = (h - np.maximum(c, o)) / c
        f7 = (-us.rolling(20, min_periods=10).std()).rank(axis=1, pct=True)

        # f8: 下影线稳定性(负)
        ls = (np.minimum(c, o) - l) / c
        f8 = (-ls.rolling(20, min_periods=10).std()).rank(axis=1, pct=True)

        # f9: Amihud非流动性(正)
        amihud = c.pct_change().abs() / (v * c + 1e-12)
        f9 = amihud.rolling(20, min_periods=10).mean().rank(axis=1, pct=True)

        # f10: APM
        morning_ret = o / c.shift(1) - 1
        afternoon_ret = c / o - 1
        apm_raw = morning_ret.rank(axis=1, pct=True) - afternoon_ret.rank(axis=1, pct=True)
        dr = (h - l) / c
        vw = 1.0 / (dr.rolling(5).mean() + 1e-8)
        vw = vw / vw.mean()
        orr = abs(o - c.shift(1)) / c.shift(1)
        fr = (h - l) / c.shift(1)
        rr = orr / (fr + 1e-8)
        f10 = (apm_raw * vw).rank(axis=1, pct=True) + rr.rank(axis=1, pct=True)
        f10 = f10.rank(axis=1, pct=True)

        # f11: ConceptCount (skip if not available)
        f11 = pd.DataFrame(0.5, index=c.index, columns=c.columns)

        # f12: Auction融合 (skip if not available)
        f12 = pd.DataFrame(0.5, index=c.index, columns=c.columns)

        # f13: 理想振幅
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
        f13 = (low_amp_mean - high_amp_mean).rank(axis=1, pct=True)

        # f14: 特质波动率
        ret = c.pct_change()
        mkt_ret = ret.mean(axis=1)
        mkt_ret_df = pd.DataFrame(
            {col: mkt_ret.values for col in c.columns}, index=c.index
        )
        stock_vol = ret.rolling(60, min_periods=60).std(ddof=1)
        corr = ret.rolling(60, min_periods=60).corr(mkt_ret_df)
        residual_vol = stock_vol * np.sqrt(np.maximum(1.0 - corr ** 2, 0.0))
        f14 = (-residual_vol).rank(axis=1, pct=True)

        # ── 新增资金流因子 ──

        # f15: 主力资金流v2
        flow = panel.get("main_net_flow")
        mcap = panel.get("mcap_yi")
        if flow is not None and mcap is not None:
            base_f15 = mcap.rank(axis=1, pct=True) - flow.rank(axis=1, pct=True)
            vol_surge = (v / v.rolling(5).mean()).rank(axis=1, pct=True)
            f15 = (base_f15 * vol_surge).rank(axis=1, pct=True)
        else:
            f15 = pd.DataFrame(0.5, index=c.index, columns=c.columns)

        # f16: 资金换手交互v2
        if flow is not None and mcap is not None:
            flow_intensity = flow / mcap.replace(0, np.nan)
            base_f16 = mcap.rank(axis=1, pct=True) - flow_intensity.rank(axis=1, pct=True)
            mom = (c / c.rolling(20).mean()).rank(axis=1, pct=True)
            f16 = (base_f16 * mom).rank(axis=1, pct=True)
        else:
            f16 = pd.DataFrame(0.5, index=c.index, columns=c.columns)

        # ── 复合 ──
        composite = (
            f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9
            + f10 + f11 + f12 + f13 + f14 + f15 + f16
        ) / 16.0

        # Cross-sectional signals
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

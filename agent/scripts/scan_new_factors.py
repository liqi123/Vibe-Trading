"""新因子扫描器 — 批量测试候选因子IC

测试维度：
1. 价格模式：突破、反转、动量
2. 成交量模式：量价背离、量能聚集
3. 波动率模式：波动率变化、波动率聚类
4. 跨截面：相对强度、行业轮动
5. 时间序列：自相关、趋势强度
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("scan_factors")

UNIVERSE = "all-a-share"
PERIOD = "2025-01-02/2026-07-10"


def _compute_ic_series(factor, forward_ret):
    ic_values = []
    valid_dates = []
    for date in factor.index:
        if date not in forward_ret.index:
            continue
        f = factor.loc[date]
        r = forward_ret.loc[date]
        mask = f.notna() & r.notna()
        if mask.sum() < 10:
            continue
        ic = f[mask].corr(r[mask], method="spearman")
        if not np.isnan(ic):
            ic_values.append(ic)
            valid_dates.append(date)
    return pd.Series(ic_values, index=pd.DatetimeIndex(valid_dates), name="ic")


def define_factors() -> dict[str, callable]:
    """定义所有候选因子"""

    def f_price_momentum_5d(panel):
        """5日动量"""
        c = panel["close"]
        return (c / c.shift(5) - 1).rank(axis=1, pct=True)

    def f_price_momentum_20d(panel):
        """20日动量"""
        c = panel["close"]
        return (c / c.shift(20) - 1).rank(axis=1, pct=True)

    def f_price_reversal_5d(panel):
        """5日反转（负动量）"""
        c = panel["close"]
        return (-(c / c.shift(5) - 1)).rank(axis=1, pct=True)

    def f_price_reversal_20d(panel):
        """20日反转"""
        c = panel["close"]
        return (-(c / c.shift(20) - 1)).rank(axis=1, pct=True)

    def f_vol_surge(panel):
        """成交量突增：vol/MA20"""
        v = panel["volume"]
        return (v / v.rolling(20).mean()).rank(axis=1, pct=True)

    def f_vol_dry(panel):
        """成交量萎缩：-vol/MA20"""
        v = panel["volume"]
        return (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

    def f_vol_price_divergence(panel):
        """量价背离：价格涨+量缩"""
        c = panel["close"]
        v = panel["volume"]
        price_chg = (c / c.shift(5) - 1).rank(axis=1, pct=True)
        vol_chg = (-(v / v.shift(5) - 1)).rank(axis=1, pct=True)
        return (price_chg * vol_chg).rank(axis=1, pct=True)

    def f_high_low_range(panel):
        """振幅：(high-low)/close"""
        h = panel["high"]
        l = panel["low"]
        c = panel["close"]
        return ((h - l) / c).rolling(10).mean().rank(axis=1, pct=True)

    def f_volatility_expansion(panel):
        """波动率扩张：std(ret,5)/std(ret,20)"""
        c = panel["close"]
        ret = c.pct_change()
        short_vol = ret.rolling(5).std()
        long_vol = ret.rolling(20).std()
        return (short_vol / long_vol.replace(0, np.nan)).rank(axis=1, pct=True)

    def f_volatility_contraction(panel):
        """波动率收缩：-std(ret,5)/std(ret,20)"""
        c = panel["close"]
        ret = c.pct_change()
        short_vol = ret.rolling(5).std()
        long_vol = ret.rolling(20).std()
        return (-(short_vol / long_vol.replace(0, np.nan))).rank(axis=1, pct=True)

    def f_trend_strength(panel):
        """趋势强度：|close-MA20|/MA20"""
        c = panel["close"]
        ma20 = c.rolling(20).mean()
        return (abs(c - ma20) / ma20).rank(axis=1, pct=True)

    def f_trend_consistency(panel):
        """趋势一致性：连续上涨天数/20"""
        c = panel["close"]
        up = (c > c.shift(1)).astype(float)
        return up.rolling(20).mean().rank(axis=1, pct=True)

    def f_relative_strength(panel):
        """相对强度：close/MA60 vs 市场均值"""
        c = panel["close"]
        rs = c / c.rolling(60).mean()
        mkt_rs = rs.mean(axis=1)
        mkt_rs_df = pd.DataFrame({col: mkt_rs.values for col in c.columns}, index=c.index)
        return (rs - mkt_rs_df).rank(axis=1, pct=True)

    def f_gap_momentum(panel):
        """跳空动量：open/prev_close"""
        o = panel["open"]
        c = panel["close"]
        return (o / c.shift(1) - 1).rank(axis=1, pct=True)

    def f_shadow_stability(panel):
        """影线稳定性：-std(upper_shadow, 20)"""
        h = panel["high"]
        l = panel["low"]
        c = panel["close"]
        o = panel["open"]
        upper = (h - np.maximum(c, o)) / c
        lower = (np.minimum(c, o) - l) / c
        return (-upper.rolling(20).std()).rank(axis=1, pct=True)

    def f_amihud_illiquidity(panel):
        """Amihud非流动性"""
        c = panel["close"]
        v = panel["volume"]
        amihud = c.pct_change().abs() / (v * c + 1e-12)
        return amihud.rolling(20).mean().rank(axis=1, pct=True)

    def f_momentum_volatility(panel):
        """动量波动率：ret*vol"""
        c = panel["close"]
        v = panel["volume"]
        ret = c.pct_change()
        vol_ret = ret.rolling(20).std()
        return (ret.rolling(5).mean() * vol_ret).rank(axis=1, pct=True)

    def f_volume_price_corr(panel):
        """量价相关性：corr(close, volume, 10)"""
        c = panel["close"]
        v = panel["volume"]
        return c.rolling(10).corr(v).rank(axis=1, pct=True)

    def f_price_acceleration(panel):
        """价格加速度：ret - ret.shift(1)"""
        c = panel["close"]
        ret = c.pct_change()
        return (ret - ret.shift(1)).rolling(5).mean().rank(axis=1, pct=True)

    def f_volume_autocorrelation(panel):
        """成交量自相关：autocorr(volume, 5)"""
        v = panel["volume"]
        return v.rolling(20).apply(lambda x: x.autocorr(lag=5) if len(x) >= 5 else np.nan, raw=False).rank(axis=1, pct=True)

    return {
        "price_momentum_5d": f_price_momentum_5d,
        "price_momentum_20d": f_price_momentum_20d,
        "price_reversal_5d": f_price_reversal_5d,
        "price_reversal_20d": f_price_reversal_20d,
        "vol_surge": f_vol_surge,
        "vol_dry": f_vol_dry,
        "vol_price_divergence": f_vol_price_divergence,
        "high_low_range": f_high_low_range,
        "volatility_expansion": f_volatility_expansion,
        "volatility_contraction": f_volatility_contraction,
        "trend_strength": f_trend_strength,
        "trend_consistency": f_trend_consistency,
        "relative_strength": f_relative_strength,
        "gap_momentum": f_gap_momentum,
        "shadow_stability": f_shadow_stability,
        "amihud_illiquidity": f_amihud_illiquidity,
        "momentum_volatility": f_momentum_volatility,
        "volume_price_corr": f_volume_price_corr,
        "price_acceleration": f_price_acceleration,
        "volume_autocorrelation": f_volume_autocorrelation,
    }


def main():
    t0 = time.time()
    log.info("=" * 80)
    log.info("新因子扫描器")
    log.info("Period: %s", PERIOD)
    log.info("=" * 80)

    # ── 1. 加载数据 ──
    log.info("\n[1/3] 加载数据 ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    close = panel["close"]
    n_stocks = close.shape[1]
    n_days = close.shape[0]
    log.info("  OHLCV: %d 只 × %d 日", n_stocks, n_days)

    # ── 2. 计算因子 ──
    log.info("\n[2/3] 计算因子 ...")
    forward_ret = close.pct_change(periods=1).shift(-1)

    factors = define_factors()
    results = []

    for name, compute_fn in factors.items():
        log.info("  %s ...", name)
        try:
            factor_df = compute_fn(panel)
        except Exception as exc:
            log.warning("    failed: %s", exc)
            continue

        nan_pct = factor_df.isna().sum().sum() / (factor_df.shape[0] * factor_df.shape[1]) * 100
        if nan_pct > 90:
            log.warning("    skip: NaN %.1f%%", nan_pct)
            continue

        ic_series = _compute_ic_series(factor_df, forward_ret)
        if ic_series.empty or len(ic_series) < 30:
            log.warning("    skip: IC series too short")
            continue

        ic_mean = ic_series.mean()
        ic_std = ic_series.std(ddof=1)
        ir = ic_mean / ic_std if ic_std > 0 else 0.0
        ic_pos_ratio = (ic_series > 0).mean()
        n = len(ic_series)
        t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 0 else 0.0

        results.append({
            "name": name,
            "ic_mean": round(ic_mean, 4),
            "ir": round(ir, 4),
            "ic_pos_ratio": round(ic_pos_ratio, 4),
            "t_stat": round(t_stat, 2),
            "n_days": n,
            "nan_pct": round(nan_pct, 1),
        })

        status = "✅" if abs(t_stat) > 2 else " "
        log.info("    %s IC=%.4f IR=%.4f IC+=%.2f t=%.2f n=%d",
                 status, ic_mean, ir, ic_pos_ratio, t_stat, n)

    # ── 3. 报告 ──
    log.info("\n" + "=" * 100)
    log.info("因子扫描结果")
    log.info("=" * 100)
    log.info(f"{'Factor':30s} {'IC':>8s} {'IR':>8s} {'IC+%':>6s} {'t':>6s} {'n':>5s} {'NaN%':>6s}")
    log.info("-" * 100)
    results.sort(key=lambda r: abs(r["t_stat"]), reverse=True)
    for r in results:
        status = "✅" if abs(r["t_stat"]) > 2 else " "
        log.info(f"{status} {r['name']:28s} {r['ic_mean']:8.4f} {r['ir']:8.4f} "
                 f"{r['ic_pos_ratio']:6.2f} {r['t_stat']:6.2f} {r['n_days']:5d} "
                 f"{r['nan_pct']:6.1f}")

    # 保存结果
    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "factor_scan"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps({
        "period": PERIOD,
        "n_stocks": n_stocks,
        "n_days": n_days,
        "results": results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

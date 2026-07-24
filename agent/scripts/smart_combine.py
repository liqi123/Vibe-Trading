"""智能因子组合 — 与14因子低相关的因子组合

策略：
1. 计算每个新因子与14因子的相关性
2. 选择低相关性因子（|corr| < 0.3）
3. 组合这些因子
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("smart_combine")

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


def run_backtest(factor_df, close, top_pct=0.05, commission=0.0015, slippage=0.001):
    """运行回测"""
    returns = close.pct_change()
    positions = pd.DataFrame(0.0, index=factor_df.index, columns=factor_df.columns)
    for date in factor_df.index:
        row = factor_df.loc[date].dropna()
        if len(row) < 10:
            continue
        n_select = max(1, int(len(row) * top_pct))
        top_stocks = row.nlargest(n_select).index
        positions.loc[date, top_stocks] = 1.0 / n_select

    portfolio_returns = (positions.shift(1) * returns).sum(axis=1)
    turnover = positions.diff().abs().sum(axis=1) / 2
    cost = turnover * (commission + slippage)
    portfolio_returns -= cost

    cumulative = (1 + portfolio_returns).cumprod()
    total_return = cumulative.iloc[-1] - 1
    n_days = len(portfolio_returns.dropna())
    annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
    annual_vol = portfolio_returns.std() * np.sqrt(252)
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0
    max_drawdown = (cumulative / cumulative.cummax() - 1).min()
    win_rate = (portfolio_returns > 0).mean()

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "win_rate": round(win_rate * 100, 1),
        "n_days": n_days,
    }


def main():
    from strategies.composite_14factor import compute_14factor

    t0 = time.time()
    log.info("=" * 80)
    log.info("智能因子组合 — 低相关性增强")
    log.info("Period: %s", PERIOD)
    log.info("=" * 80)

    # ── 1. 加载数据 ──
    log.info("\n[1/4] 加载数据 ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    c = panel["close"]
    v = panel["volume"]
    o = panel["open"]
    h = panel["high"]
    l = panel["low"]
    log.info("  OHLCV: %d 只 × %d 日", c.shape[1], c.shape[0])

    # ── 2. 计算14因子作为基准 ──
    log.info("\n[2/4] 计算14因子基准 ...")
    factor_14 = compute_14factor(panel)

    # ── 3. 定义候选因子并计算相关性 ──
    log.info("\n[3/4] 计算候选因子与14因子的相关性 ...")

    candidates = {}

    # 候选1: shadow_stability
    upper = (h - np.maximum(c, o)) / c
    f_shadow = (-upper.rolling(20).std()).rank(axis=1, pct=True)
    candidates["shadow_stability"] = f_shadow

    # 候选2: price_reversal_20d
    f_reversal = (-(c / c.shift(20) - 1)).rank(axis=1, pct=True)
    candidates["price_reversal_20d"] = f_reversal

    # 候选3: gap_momentum
    f_gap = (o / c.shift(1) - 1).rank(axis=1, pct=True)
    candidates["gap_momentum"] = f_gap

    # 候选4: vol_dry
    f_vol_dry = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)
    candidates["vol_dry"] = f_vol_dry

    # 候选5: volume_price_corr (翻转)
    f_vpc = (-c.rolling(10).corr(v)).rank(axis=1, pct=True)
    candidates["volume_price_corr"] = f_vpc

    # 候选6: high_low_range (翻转)
    f_hlr = (-((h - l) / c).rolling(10).mean()).rank(axis=1, pct=True)
    candidates["high_low_range"] = f_hlr

    # 候选7: volatility_contraction
    ret = c.pct_change()
    short_vol = ret.rolling(5).std()
    long_vol = ret.rolling(20).std()
    f_volcon = (short_vol / long_vol.replace(0, np.nan)).rank(axis=1, pct=True)
    candidates["volatility_contraction"] = f_volcon

    # 候选8: relative_strength
    rs = c / c.rolling(60).mean()
    mkt_rs = rs.mean(axis=1)
    mkt_rs_df = pd.DataFrame({col: mkt_rs.values for col in c.columns}, index=c.index)
    f_rs = (rs - mkt_rs_df).rank(axis=1, pct=True)
    candidates["relative_strength"] = f_rs

    # 计算与14因子的相关性
    correlations = {}
    for name, f in candidates.items():
        # 逐日计算截面相关性，取均值
        corrs = []
        for date in factor_14.index:
            if date not in f.index:
                continue
            row14 = factor_14.loc[date]
            rowF = f.loc[date]
            mask = row14.notna() & rowF.notna()
            if mask.sum() < 10:
                continue
            corr = row14[mask].corr(rowF[mask])
            if not np.isnan(corr):
                corrs.append(corr)
        avg_corr = np.mean(corrs) if corrs else 0
        correlations[name] = avg_corr
        log.info("  %s: corr with 14F = %.3f", name, avg_corr)

    # 选择低相关性因子（|corr| < 0.3）
    low_corr_factors = {k: v for k, v in candidates.items() if abs(correlations[k]) < 0.3}
    log.info("\n  低相关性因子（|corr| < 0.3）: %d 个", len(low_corr_factors))
    for name in low_corr_factors:
        log.info("    %s (corr=%.3f)", name, correlations[name])

    # ── 4. 组合并回测 ──
    log.info("\n[4/4] 组合并回测 ...")

    results = {}

    # 14因子基准
    results["14-Factor"] = {"factor": factor_14}

    # 新因子等权组合（只用低相关性因子）
    if low_corr_factors:
        new_composite = sum(low_corr_factors.values()) / len(low_corr_factors)
        results["New-LowCorr"] = {"factor": new_composite}

    # 14因子 + 新因子组合
    if low_corr_factors:
        new_part = sum(low_corr_factors.values()) / len(low_corr_factors)
        # 70% 14因子 + 30% 新因子
        combined = factor_14 * 0.7 + new_part * 0.3
        results["14F+New-70/30"] = {"factor": combined}

        # 50% 14因子 + 50% 新因子
        combined2 = factor_14 * 0.5 + new_part * 0.5
        results["14F+New-50/50"] = {"factor": combined2}

    # 计算IC和回测
    forward_ret = c.pct_change(periods=1).shift(-1)
    bt_results = {}

    for name, data in results.items():
        factor_df = data["factor"]

        # IC
        ic_series = _compute_ic_series(factor_df, forward_ret)
        if not ic_series.empty:
            ic_mean = ic_series.mean()
            ic_std = ic_series.std(ddof=1)
            ir = ic_mean / ic_std if ic_std > 0 else 0.0
            t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0.0
        else:
            ic_mean, ir, t_stat = 0, 0, 0

        # 回测
        bt = run_backtest(factor_df, c)
        bt["ic"] = round(ic_mean, 4)
        bt["ir"] = round(ir, 4)
        bt["t"] = round(t_stat, 2)
        bt_results[name] = bt

        log.info("  %s: IC=%.4f IR=%.4f t=%.2f | 收益=%.1f%% 夏普=%.2f",
                 name, ic_mean, ir, t_stat, bt["total_return"], bt["sharpe"])

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("对比结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':20s} {'IC':>8s} {'IR':>8s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'回撤':>8s} {'胜率':>6s}")
    log.info("-" * 100)
    for name, bt in bt_results.items():
        log.info(f"{name:20s} {bt['ic']:8.4f} {bt['ir']:8.4f} "
                 f"{bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}% "
                 f"{bt['win_rate']:5.1f}%")

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    # 保存结果
    out_dir = Path("output") / "smart_combine"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    save_data = {k: {kk: vv for kk, vv in v.items() if kk != "factor"} for k, v in bt_results.items()}
    out_path.write_text(json.dumps({"period": PERIOD, "correlations": correlations, "results": save_data}, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

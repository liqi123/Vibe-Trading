"""低相关性因子扫描 — 寻找与14因子负相关的diversifier

策略：
1. 定义更多候选因子
2. 计算与14因子的相关性
3. 筛选负相关因子
4. 组合测试
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("scan_diversifiers")

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
    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
    }


def main():
    from strategies.composite.composite_14factor import compute_14factor

    t0 = time.time()
    log.info("=" * 80)
    log.info("低相关性因子扫描")
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

    # ── 2. 计算14因子基准 ──
    log.info("\n[2/4] 计算14因子基准 ...")
    factor_14 = compute_14factor(panel)

    # ── 3. 定义更多候选因子 ──
    log.info("\n[3/4] 计算候选因子相关性 ...")

    candidates = {}

    # === 波动率类 ===
    # 9. 波动率收缩 (已验证)
    ret = c.pct_change()
    short_vol = ret.rolling(5).std()
    long_vol = ret.rolling(20).std()
    candidates["volatility_contraction"] = (short_vol / long_vol.replace(0, np.nan)).rank(axis=1, pct=True)

    # 10. 波动率扩张 (反向)
    candidates["volatility_expansion"] = (-(short_vol / long_vol.replace(0, np.nan))).rank(axis=1, pct=True)

    # 11. 低波动率偏好
    vol_60 = ret.rolling(60).std()
    candidates["low_vol_preference"] = (-vol_60).rank(axis=1, pct=True)

    # 12. 波动率变化率
    vol_change = short_vol / short_vol.shift(10).replace(0, np.nan)
    candidates["vol_change_rate"] = (-vol_change).rank(axis=1, pct=True)

    # === 趋势类 ===
    # 13. 趋势衰减
    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    trend_strength = (ma5 - ma20) / ma20
    candidates["trend_decay"] = (-abs(trend_strength)).rank(axis=1, pct=True)

    # 14. 均线收敛
    ma5_std = ma5.rolling(10).std()
    candidates["ma_convergence"] = (-ma5_std).rank(axis=1, pct=True)

    # 15. 价格位置
    price_pos = (c - l.rolling(20).min()) / (h.rolling(20).max() - l.rolling(20).min() + 1e-10)
    candidates["price_position"] = (-(price_pos - 0.5)).rank(axis=1, pct=True)

    # === 成交量类 ===
    # 16. 成交量稳定性
    vol_std = v.rolling(20).std()
    vol_mean = v.rolling(20).mean()
    candidates["vol_stability"] = (-(vol_std / vol_mean.replace(0, np.nan))).rank(axis=1, pct=True)

    # 17. 成交量趋势
    vol_trend = v.rolling(5).mean() / v.rolling(20).mean()
    candidates["vol_trend"] = (-(vol_trend - 1)).rank(axis=1, pct=True)

    # 18. 量价背离强度
    price_chg = c.pct_change(5)
    vol_chg = v.pct_change(5)
    divergence = price_chg - vol_chg
    candidates["vol_price_divergence"] = divergence.rank(axis=1, pct=True)

    # === 动量类 ===
    # 19. 动量反转
    mom_20 = c / c.shift(20) - 1
    candidates["momentum_reversal"] = (-mom_20).rank(axis=1, pct=True)

    # 20. 动量衰减
    mom_5 = c / c.shift(5) - 1
    mom_20 = c / c.shift(20) - 1
    mom_decay = mom_5 - mom_20
    candidates["momentum_decay"] = (-mom_decay).rank(axis=1, pct=True)

    # 21. 动量一致性
    ret_sign = (c.pct_change() > 0).astype(float)
    candidates["momentum_consistency"] = ret_sign.rolling(20).mean().rank(axis=1, pct=True)

    # === 流动性类 ===
    # 22. 流动性变化
    amihud = c.pct_change().abs() / (v * c + 1e-12)
    amihud_20 = amihud.rolling(20).mean()
    amihud_5 = amihud.rolling(5).mean()
    liq_change = amihud_5 / amihud_20.replace(0, np.nan)
    candidates["liquidity_change"] = (-liq_change).rank(axis=1, pct=True)

    # 23. 流动性稳定性
    candidates["liquidity_stability"] = (-(amihud.rolling(20).std() / amihud_20.replace(0, np.nan))).rank(axis=1, pct=True)

    # === 振幅类 ===
    # 24. 振幅收缩
    amplitude = (h - l) / c
    amp_5 = amplitude.rolling(5).mean()
    amp_20 = amplitude.rolling(20).mean()
    candidates["amplitude_contraction"] = (-(amp_5 / amp_20.replace(0, np.nan))).rank(axis=1, pct=True)

    # 25. 振幅稳定性
    candidates["amplitude_stability"] = (-(amplitude.rolling(20).std() / amplitude.rolling(20).mean().replace(0, np.nan))).rank(axis=1, pct=True)

    # 计算相关性
    correlations = {}
    for name, f in candidates.items():
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

    # 按相关性排序
    sorted_corrs = sorted(correlations.items(), key=lambda x: x[1])
    log.info("\n  所有因子相关性（与14因子）:")
    for name, corr in sorted_corrs:
        marker = "★" if corr < -0.1 else " " if corr < 0.3 else "✗"
        log.info("    %s %s: %.3f", marker, name, corr)

    # 筛选负相关因子
    neg_corr = {k: v for k, v in correlations.items() if v < -0.1}
    log.info("\n  负相关因子（corr < -0.1）: %d 个", len(neg_corr))

    # ── 4. 组合测试 ──
    log.info("\n[4/4] 组合测试 ...")
    forward_ret = c.pct_change(periods=1).shift(-1)

    results = {}

    # 14因子基准
    ic_14 = _compute_ic_series(factor_14, forward_ret)
    ic_mean_14 = ic_14.mean()
    ir_14 = ic_mean_14 / ic_14.std() if ic_14.std() > 0 else 0
    bt_14 = run_backtest(factor_14, c)
    results["14-Factor"] = {"ic": ic_mean_14, "ir": ir_14, **bt_14}

    # 测试每个负相关因子的组合效果
    for name in neg_corr:
        f = candidates[name]
        # 70% 14因子 + 30% 新因子
        combined = factor_14 * 0.7 + f * 0.3
        ic_comb = _compute_ic_series(combined, forward_ret)
        ic_mean_comb = ic_comb.mean()
        ir_comb = ic_mean_comb / ic_comb.std() if ic_comb.std() > 0 else 0
        bt_comb = run_backtest(combined, c)
        results[f"14F+{name}"] = {"ic": ic_mean_comb, "ir": ir_comb, **bt_comb}

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("组合对比结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':35s} {'IC':>8s} {'IR':>8s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'回撤':>8s}")
    log.info("-" * 100)
    results_sorted = sorted(results.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for name, bt in results_sorted:
        log.info(f"{name:35s} {bt['ic']:8.4f} {bt['ir']:8.4f} "
                 f"{bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}%")

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "diversifier_scan"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    save_results = {k: {kk: vv for kk, vv in v.items()} for k, v in results.items()}
    out_path.write_text(json.dumps({
        "period": PERIOD,
        "correlations": correlations,
        "results": save_results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

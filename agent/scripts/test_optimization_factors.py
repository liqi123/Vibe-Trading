"""测试优化因子 — 低波动/中性化/组合"""
from __future__ import annotations

import json
import logging
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test_optimization")

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
    t0 = time.time()
    log.info("=" * 80)
    log.info("测试优化因子")
    log.info("Period: %s", PERIOD)
    log.info("=" * 80)

    # ── 1. 加载数据 ──
    log.info("\n[1/3] 加载数据 ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    c = panel["close"]
    log.info("  OHLCV: %d 只 × %d 日", c.shape[1], c.shape[0])

    # ── 2. 计算因子 ──
    log.info("\n[2/3] 计算因子 ...")
    from strategies.composite_14factor import compute_14factor
    from strategies.composite_17factor_optimal import compute_17factor_optimal
    from strategies.composite_21factor_lowvol import compute_21factor_lowvol
    from strategies.composite_22factor_neutral import compute_22factor_neutral

    forward_ret = c.pct_change(periods=1).shift(-1)
    results = {}

    for name, compute_fn in [
        ("14-Factor", compute_14factor),
        ("17F-Optimal", compute_17factor_optimal),
        ("21F-LowVol", compute_21factor_lowvol),
        ("22F-Neutral", compute_22factor_neutral),
    ]:
        log.info("  计算 %s ...", name)
        try:
            factor_df = compute_fn(panel)
        except Exception as exc:
            log.warning("  failed: %s", exc)
            continue

        ic_series = _compute_ic_series(factor_df, forward_ret)
        ic_mean = ic_series.mean()
        ic_std = ic_series.std(ddof=1)
        ir = ic_mean / ic_std if ic_std > 0 else 0
        t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0

        bt = run_backtest(factor_df, c)
        bt["ic"] = round(ic_mean, 4)
        bt["ir"] = round(ir, 4)
        bt["t"] = round(t_stat, 2)
        results[name] = bt

        log.info("    IC=%.4f IR=%.4f t=%.2f | 收益=%.1f%% 夏普=%.2f",
                 ic_mean, ir, t_stat, bt["total_return"], bt["sharpe"])

    # ── 3. 测试组合 ──
    log.info("\n[3/3] 测试组合 ...")

    # 17F-Optimal + 21F-LowVol
    f17 = compute_17factor_optimal(panel)
    f21 = compute_21factor_lowvol(panel)
    combined = f17 * 0.6 + f21 * 0.4
    ic_comb = _compute_ic_series(combined, forward_ret)
    bt_comb = run_backtest(combined, c)
    bt_comb["ic"] = round(ic_comb.mean(), 4)
    bt_comb["ir"] = round(ic_comb.mean() / ic_comb.std() if ic_comb.std() > 0 else 0, 4)
    bt_comb["t"] = round(ic_comb.mean() / (ic_comb.std() / np.sqrt(len(ic_comb))) if ic_comb.std() > 0 else 0, 2)
    results["17F+21F-60/40"] = bt_comb

    log.info("  17F+21F-60/40: IC=%.4f IR=%.4f | 收益=%.1f%% 夏普=%.2f",
             bt_comb["ic"], bt_comb["ir"], bt_comb["total_return"], bt_comb["sharpe"])

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("测试结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':20s} {'IC':>8s} {'IR':>8s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'回撤':>8s}")
    log.info("-" * 100)
    results_sorted = sorted(results.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for name, bt in results_sorted:
        log.info(f"{name:20s} {bt['ic']:8.4f} {bt['ir']:8.4f} "
                 f"{bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}%")

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "optimization_factors"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps({"period": PERIOD, "results": results}, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

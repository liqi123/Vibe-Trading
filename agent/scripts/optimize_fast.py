"""因子组合快速优化 — 跳过动态权重"""
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
log = logging.getLogger("optimize_fast")

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
    log.info("因子组合快速优化")
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

    f14 = compute_14factor(panel)

    # 新增diversifier
    ret = c.pct_change()
    mom_5 = c / c.shift(5) - 1
    mom_20 = c / c.shift(20) - 1
    short_vol = ret.rolling(5).std()
    long_vol = ret.rolling(20).std()
    ret_sign = (c.pct_change() > 0).astype(float)

    factors = {
        "f14": f14,
        "momentum_decay": (-(mom_5 - mom_20)).rank(axis=1, pct=True),
        "volatility_contraction": (short_vol / long_vol.replace(0, np.nan)).rank(axis=1, pct=True),
        "momentum_consistency": ret_sign.rolling(20).mean().rank(axis=1, pct=True),
        "vol_concentration": (c.rolling(5).max() / c.rolling(20).mean().replace(0, np.nan)).rank(axis=1, pct=True),
        "vol_price_mom": ((c.rolling(5).mean() / c.rolling(20).mean()) * (c / c.shift(5))).rank(axis=1, pct=True),
        "vol_regime": (short_vol / ret.rolling(60).std().replace(0, np.nan)).rank(axis=1, pct=True),
    }

    # 计算相关性
    forward_ret = c.pct_change(periods=1).shift(-1)
    correlations = {}
    ic_values = {}
    for name, f in factors.items():
        if name == "f14":
            continue
        corrs = []
        for date in f14.index:
            if date not in f.index:
                continue
            row14 = f14.loc[date]
            rowF = f.loc[date]
            mask = row14.notna() & rowF.notna()
            if mask.sum() < 10:
                continue
            corr = row14[mask].corr(rowF[mask])
            if not np.isnan(corr):
                corrs.append(corr)
        correlations[name] = np.mean(corrs) if corrs else 0

        # IC
        ic = _compute_ic_series(f, forward_ret)
        ic_values[name] = {"ic": ic.mean(), "ir": ic.mean() / ic.std() if ic.std() > 0 else 0}

    log.info("  因子相关性和IC:")
    for name in sorted(correlations.keys(), key=lambda x: correlations[x]):
        ic = ic_values[name]["ic"]
        ir = ic_values[name]["ir"]
        log.info("    %s: corr=%.3f IC=%.4f IR=%.4f", name, correlations[name], ic, ir)

    # ── 3. 组合测试 ──
    log.info("\n[3/3] 组合测试 ...")

    results = {}

    # 14F基准
    bt_14 = run_backtest(f14, c)
    ic_14 = _compute_ic_series(f14, forward_ret)
    bt_14["ic"] = round(ic_14.mean(), 4)
    bt_14["ir"] = round(ic_14.mean() / ic_14.std() if ic_14.std() > 0 else 0, 4)
    results["14-Factor"] = bt_14

    # 方向1: diversifier组合
    # 最优: 14F + momentum_decay 70/30
    comb1 = f14 * 0.7 + factors["momentum_decay"] * 0.3
    ic1 = _compute_ic_series(comb1, forward_ret)
    bt1 = run_backtest(comb1, c)
    bt1["ic"] = round(ic1.mean(), 4)
    bt1["ir"] = round(ic1.mean() / ic1.std() if ic1.std() > 0 else 0, 4)
    results["14F+MD-70/30"] = bt1

    # 多diversifier: 14F + top3负相关
    top3_neg = sorted(correlations.keys(), key=lambda x: correlations[x])[:3]
    comb2 = f14 * 0.4
    for name in top3_neg:
        comb2 += factors[name] * 0.2
    ic2 = _compute_ic_series(comb2, forward_ret)
    bt2 = run_backtest(comb2, c)
    bt2["ic"] = round(ic2.mean(), 4)
    bt2["ir"] = round(ic2.mean() / ic2.std() if ic2.std() > 0 else 0, 4)
    results["14F+Top3Neg-40/20/20/20"] = bt2

    # 方向2: ML组合（IC加权）
    ic_weights = {}
    for name in factors:
        ic = _compute_ic_series(factors[name], forward_ret)
        ic_weights[name] = abs(ic.mean())
    total_ic = sum(ic_weights.values())
    ic_weights = {k: v / total_ic for k, v in ic_weights.items()}

    ml_combined = sum(factors[name] * ic_weights[name] for name in factors)
    ml_combined = ml_combined.rank(axis=1, pct=True)
    ic_ml = _compute_ic_series(ml_combined, forward_ret)
    bt_ml = run_backtest(ml_combined, c)
    bt_ml["ic"] = round(ic_ml.mean(), 4)
    bt_ml["ir"] = round(ic_ml.mean() / ic_ml.std() if ic_ml.std() > 0 else 0, 4)
    results["ML-IC-Weighted"] = bt_ml

    # Ridge代理（只用正IC因子）
    ridge_weights = {}
    for name in factors:
        ic = _compute_ic_series(factors[name], forward_ret)
        ridge_weights[name] = max(0, ic.mean())
    total_ridge = sum(ridge_weights.values())
    if total_ridge > 0:
        ridge_weights = {k: v / total_ridge for k, v in ridge_weights.items()}

    ridge_combined = sum(factors[name] * ridge_weights[name] for name in factors)
    ridge_combined = ridge_combined.rank(axis=1, pct=True)
    ic_ridge = _compute_ic_series(ridge_combined, forward_ret)
    bt_ridge = run_backtest(ridge_combined, c)
    bt_ridge["ic"] = round(ic_ridge.mean(), 4)
    bt_ridge["ir"] = round(ic_ridge.mean() / ic_ridge.std() if ic_ridge.std() > 0 else 0, 4)
    results["ML-Ridge-Positive"] = bt_ridge

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("优化结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':30s} {'IC':>8s} {'IR':>8s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'回撤':>8s}")
    log.info("-" * 100)
    results_sorted = sorted(results.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for name, bt in results_sorted:
        log.info(f"{name:30s} {bt['ic']:8.4f} {bt['ir']:8.4f} "
                 f"{bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}%")

    # 对比提升
    best = results_sorted[0]
    log.info("\n最优: %s", best[0])
    log.info("  vs 14F: 收益 %+.1f%%  夏普 %+.2f",
             best[1]["total_return"] - bt_14["total_return"],
             best[1]["sharpe"] - bt_14["sharpe"])

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "optimize_fast"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps({
        "period": PERIOD,
        "correlations": correlations,
        "ic_weights": {k: round(v, 4) for k, v in ic_weights.items()},
        "results": results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

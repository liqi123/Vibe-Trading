"""新维度因子扫描 — 技术指标/跨截面/多时间框架/市场regime

维度1: 技术指标因子 (RSI/MACD/Bollinger/ATR)
维度2: 跨截面因子 (行业相对强度/市值中性)
维度3: 多时间框架 (短周期vs长周期信号)
维度4: 市场regime (牛熊/波动率状态)
"""
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
log = logging.getLogger("scan_new_dims")

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


def compute_new_dimension_factors(panel):
    """计算新维度因子"""
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)

    factors = {}

    # === 维度1: 技术指标因子 ===

    # RSI因子
    delta = c.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    factors["rsi_14"] = (-(rsi - 50)).rank(axis=1, pct=True)  # 低RSI看多

    # RSI背离
    rsi_ma = rsi.rolling(20).mean()
    factors["rsi_divergence"] = ((c - c.shift(20)) - (rsi - rsi.shift(20))).rank(axis=1, pct=True)

    # MACD因子
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    macd_hist = macd - signal
    factors["macd_hist"] = macd_hist.rank(axis=1, pct=True)

    # MACD交叉
    macd_cross = (macd > signal).astype(float)
    factors["macd_cross"] = macd_cross.rolling(5).mean().rank(axis=1, pct=True)

    # Bollinger Band位置
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    bb_pos = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    factors["bb_position"] = (-(bb_pos - 0.5)).rank(axis=1, pct=True)  # 低位看多

    # Bollinger Band宽度
    bb_width = (bb_upper - bb_lower) / ma20
    factors["bb_width"] = (-bb_width).rank(axis=1, pct=True)  # 窄幅看多

    # ATR因子
    tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
    if isinstance(tr, pd.Series):
        tr = pd.DataFrame({col: tr.values for col in c.columns}, index=c.index)
    atr = tr.rolling(14).mean()
    factors["atr_pct"] = (-(atr / c)).rank(axis=1, pct=True)  # 低ATR看多

    # ATR变化率
    atr_change = atr / atr.shift(10).replace(0, np.nan)
    factors["atr_change"] = (-atr_change).rank(axis=1, pct=True)

    # === 维度2: 跨截面因子 ===

    # 相对强度 vs 市场
    rs = c / c.shift(20)
    mkt_rs = rs.mean(axis=1)
    mkt_rs_df = pd.DataFrame({col: mkt_rs.values for col in c.columns}, index=c.index)
    factors["relative_strength"] = (rs - mkt_rs_df).rank(axis=1, pct=True)

    # 市值中性动量
    mom_20 = c / c.shift(20) - 1
    factors["size_neutral_mom"] = mom_20.rank(axis=1, pct=True)

    # 行业内相对强度（简化：用全市场排名）
    factors["cross_sectional_rank"] = c.rank(axis=1, pct=True)

    # === 维度3: 多时间框架 ===

    # 短期动量（5日）
    factors["mom_5d"] = (c / c.shift(5) - 1).rank(axis=1, pct=True)

    # 中期动量（20日）
    factors["mom_20d"] = (c / c.shift(20) - 1).rank(axis=1, pct=True)

    # 长期动量（60日）
    factors["mom_60d"] = (c / c.shift(60) - 1).rank(axis=1, pct=True)

    # 动量一致性（多时间框架同向）
    mom5_sign = (c / c.shift(5) - 1 > 0).astype(float)
    mom20_sign = (c / c.shift(20) - 1 > 0).astype(float)
    mom60_sign = (c / c.shift(60) - 1 > 0).astype(float)
    factors["mom_consistency"] = (mom5_sign + mom20_sign + mom60_sign).rank(axis=1, pct=True)

    # 短期反转
    factors["reversal_5d"] = (-(c / c.shift(5) - 1)).rank(axis=1, pct=True)

    # === 维度4: 市场regime ===

    # 波动率状态
    ret = c.pct_change()
    vol_20 = ret.rolling(20).std()
    vol_60 = ret.rolling(60).std()
    factors["vol_regime"] = (vol_20 / vol_60.replace(0, np.nan)).rank(axis=1, pct=True)

    # 趋势状态
    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    trend_score = ((ma5 > ma20).astype(float) + (ma20 > ma60).astype(float)) / 2
    factors["trend_regime"] = trend_score.rank(axis=1, pct=True)

    # 市场宽度（简化：用上涨股票比例）
    up_pct = (c.pct_change() > 0).astype(float).mean(axis=1)
    if isinstance(up_pct, pd.Series):
        up_pct = pd.DataFrame({col: up_pct.values for col in c.columns}, index=c.index)
    factors["market_breadth"] = up_pct.rank(axis=1, pct=True)

    # 动量分散度
    mom_dispersion = ret.rolling(20).std()
    if isinstance(mom_dispersion, pd.Series):
        mom_dispersion = pd.DataFrame({col: mom_dispersion.values for col in c.columns}, index=c.index)
    factors["mom_dispersion"] = (-mom_dispersion).rank(axis=1, pct=True)

    return factors


def main():
    t0 = time.time()
    log.info("=" * 80)
    log.info("新维度因子扫描")
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
    log.info("\n[2/3] 计算新维度因子 ...")
    factors = compute_new_dimension_factors(panel)
    log.info("  共 %d 个因子", len(factors))

    # 计算与14F的相关性
    from strategies.composite.composite_14factor import compute_14factor
    f14 = compute_14factor(panel)
    forward_ret = c.pct_change(periods=1).shift(-1)

    correlations = {}
    ic_results = {}
    for name, f in factors.items():
        # 相关性
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
        if len(ic) > 0:
            ic_results[name] = {
                "ic": ic.mean(),
                "ir": ic.mean() / ic.std() if ic.std() > 0 else 0,
                "t": ic.mean() / (ic.std() / np.sqrt(len(ic))) if ic.std() > 0 else 0,
            }
        else:
            ic_results[name] = {"ic": 0, "ir": 0, "t": 0}

    # 按IC排序
    sorted_by_ic = sorted(ic_results.items(), key=lambda x: abs(x[1]["t"]), reverse=True)
    log.info("\n  因子排名（按|t|值）:")
    for name, res in sorted_by_ic:
        corr = correlations[name]
        marker = "★" if res["t"] > 2 or res["t"] < -2 else " "
        corr_marker = "★" if corr < -0.1 else " " if corr < 0.3 else "✗"
        log.info("    %s %s: IC=%.4f IR=%.4f t=%.2f corr=%s%.3f",
                 marker, name, res["ic"], res["ir"], res["t"], corr_marker, corr)

    # ── 3. 组合测试 ──
    log.info("\n[3/3] 组合测试 ...")

    results = {}

    # 14F基准
    bt_14 = run_backtest(f14, c)
    ic_14 = _compute_ic_series(f14, forward_ret)
    bt_14["ic"] = round(ic_14.mean(), 4)
    bt_14["ir"] = round(ic_14.mean() / ic_14.std() if ic_14.std() > 0 else 0, 4)
    results["14-Factor"] = bt_14

    # 测试新因子组合
    # 技术指标因子组合
    tech_factors = ["rsi_14", "macd_hist", "bb_position", "atr_pct"]
    tech_combined = sum(factors[f] for f in tech_factors if f in factors) / len(tech_factors)
    bt_tech = run_backtest(tech_combined, c)
    ic_tech = _compute_ic_series(tech_combined, forward_ret)
    bt_tech["ic"] = round(ic_tech.mean(), 4)
    bt_tech["ir"] = round(ic_tech.mean() / ic_tech.std() if ic_tech.std() > 0 else 0, 4)
    results["Tech-Indicator-4F"] = bt_tech

    # 多时间框架因子
    mtf_factors = ["mom_5d", "mom_20d", "mom_60d", "mom_consistency"]
    mtf_combined = sum(factors[f] for f in mtf_factors if f in factors) / len(mtf_factors)
    bt_mtf = run_backtest(mtf_combined, c)
    ic_mtf = _compute_ic_series(mtf_combined, forward_ret)
    bt_mtf["ic"] = round(ic_mtf.mean(), 4)
    bt_mtf["ir"] = round(ic_mtf.mean() / ic_mtf.std() if ic_mtf.std() > 0 else 0, 4)
    results["Multi-Timeframe-4F"] = bt_mtf

    # 14F + 新因子组合（选择负相关的）
    neg_corr_new = {k: v for k, v in correlations.items() if v < -0.1}
    if neg_corr_new:
        top_neg = list(neg_corr_new.keys())[:3]
        combined_new = f14 * 0.5
        for name in top_neg:
            combined_new += factors[name] * (0.5 / len(top_neg))
        bt_new = run_backtest(combined_new, c)
        ic_new = _compute_ic_series(combined_new, forward_ret)
        bt_new["ic"] = round(ic_new.mean(), 4)
        bt_new["ir"] = round(ic_new.mean() / ic_new.std() if ic_new.std() > 0 else 0, 4)
        results["14F+NewDim3-50/17/17/17"] = bt_new

    # 全因子等权
    all_factors = list(factors.keys())
    all_combined = sum(factors[f] for f in all_factors) / len(all_factors)
    bt_all = run_backtest(all_combined, c)
    ic_all = _compute_ic_series(all_combined, forward_ret)
    bt_all["ic"] = round(ic_all.mean(), 4)
    bt_all["ir"] = round(ic_all.mean() / ic_all.std() if ic_all.std() > 0 else 0, 4)
    results["All-NewDim-EqualWeight"] = bt_all

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("新维度组合结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':30s} {'IC':>8s} {'IR':>8s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'回撤':>8s}")
    log.info("-" * 100)
    results_sorted = sorted(results.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for name, bt in results_sorted:
        log.info(f"{name:30s} {bt['ic']:8.4f} {bt['ir']:8.4f} "
                 f"{bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}%")

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "new_dimensions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps({
        "period": PERIOD,
        "correlations": correlations,
        "ic_results": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in ic_results.items()},
        "results": results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

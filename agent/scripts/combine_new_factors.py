"""新因子组合 — 基于扫描结果构建最优组合

扫描发现的强因子（|t|>5）：
✅ 正向：
  vol_dry (IC=0.045, t=7.99) - 成交量萎缩
  shadow_stability (IC=0.052, t=5.70) - 影线稳定性
  price_reversal_20d (IC=0.042, t=5.74) - 20日反转
  gap_momentum (IC=0.027, t=5.26) - 跳空动量

✅ 反向（需翻转）：
  volume_price_corr (IC=-0.051, t=-10.28) - 量价相关性
  vol_surge (IC=-0.045, t=-7.99) - 成交量突增
  high_low_range (IC=-0.058, t=-5.76) - 振幅

组合策略：
1. 等权组合所有强因子
2. 与14因子对比
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("combine_factors")

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


def compute_new_composite(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """计算新因子组合"""
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)

    # 1. vol_dry (正向) - 成交量萎缩
    f1 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

    # 2. shadow_stability (正向) - 影线稳定性
    upper = (h - np.maximum(c, o)) / c
    f2 = (-upper.rolling(20).std()).rank(axis=1, pct=True)

    # 3. price_reversal_20d (正向) - 20日反转
    f3 = (-(c / c.shift(20) - 1)).rank(axis=1, pct=True)

    # 4. gap_momentum (正向) - 跳空动量
    f4 = (o / c.shift(1) - 1).rank(axis=1, pct=True)

    # 5. volume_price_corr (反向翻转) - 量价相关性
    f5 = (-c.rolling(10).corr(v)).rank(axis=1, pct=True)

    # 6. vol_surge (反向翻转) - 成交量突增
    f6 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

    # 7. high_low_range (反向翻转) - 振幅
    f7 = (-((h - l) / c).rolling(10).mean()).rank(axis=1, pct=True)

    # 等权组合
    composite = (f1 + f2 + f3 + f4 + f5 + f6 + f7) / 7.0
    return composite


def compute_new_composite_v2(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """新因子组合v2 - 加权组合（按IR加权）"""
    c = panel["close"].astype(float)
    v = panel["volume"].astype(float)
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    l = panel["low"].astype(float)

    # 按IR加权（IR越高权重越大）
    weights = {
        "vol_dry": 0.43,
        "shadow_stability": 0.31,
        "price_reversal_20d": 0.31,
        "gap_momentum": 0.28,
        "volume_price_corr": 0.54,  # 翻转后
        "vol_surge": 0.43,  # 翻转后
        "high_low_range": 0.30,  # 翻转后
    }
    total_weight = sum(weights.values())

    # 1. vol_dry
    f1 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

    # 2. shadow_stability
    upper = (h - np.maximum(c, o)) / c
    f2 = (-upper.rolling(20).std()).rank(axis=1, pct=True)

    # 3. price_reversal_20d
    f3 = (-(c / c.shift(20) - 1)).rank(axis=1, pct=True)

    # 4. gap_momentum
    f4 = (o / c.shift(1) - 1).rank(axis=1, pct=True)

    # 5. volume_price_corr (翻转)
    f5 = (-c.rolling(10).corr(v)).rank(axis=1, pct=True)

    # 6. vol_surge (翻转)
    f6 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)

    # 7. high_low_range (翻转)
    f7 = (-((h - l) / c).rolling(10).mean()).rank(axis=1, pct=True)

    # 加权组合
    composite = (
        f1 * weights["vol_dry"] +
        f2 * weights["shadow_stability"] +
        f3 * weights["price_reversal_20d"] +
        f4 * weights["gap_momentum"] +
        f5 * weights["volume_price_corr"] +
        f6 * weights["vol_surge"] +
        f7 * weights["high_low_range"]
    ) / total_weight
    return composite


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
    from strategies.composite.composite_14factor import compute_14factor

    t0 = time.time()
    log.info("=" * 80)
    log.info("新因子组合测试")
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
    log.info("  OHLCV: %d 只 × %d 日", close.shape[1], close.shape[0])

    # ── 2. 计算因子并测试IC ──
    log.info("\n[2/3] 计算因子并测试IC ...")
    forward_ret = close.pct_change(periods=1).shift(-1)

    results = {}
    for name, compute_fn in [
        ("14-Factor", compute_14factor),
        ("New-Composite", compute_new_composite),
        ("New-Composite-v2", compute_new_composite_v2),
    ]:
        log.info("  计算 %s ...", name)
        try:
            factor_df = compute_fn(panel)
        except Exception as exc:
            log.warning("  failed: %s", exc)
            continue

        ic_series = _compute_ic_series(factor_df, forward_ret)
        if ic_series.empty:
            continue

        ic_mean = ic_series.mean()
        ic_std = ic_series.std(ddof=1)
        ir = ic_mean / ic_std if ic_std > 0 else 0.0
        t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0.0

        results[name] = {"ic": ic_mean, "ir": ir, "t": t_stat, "factor": factor_df}
        log.info("    IC=%.4f IR=%.4f t=%.2f", ic_mean, ir, t_stat)

    # ── 3. 回测对比 ──
    log.info("\n[3/3] 回测对比 ...")
    bt_results = {}
    for name, data in results.items():
        log.info("  回测 %s ...", name)
        bt = run_backtest(data["factor"], close)
        bt["ic"] = data["ic"]
        bt["ir"] = data["ir"]
        bt["t"] = data["t"]
        bt_results[name] = bt

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
    out_dir = Path("output") / "new_factors"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    save_data = {k: {kk: vv for kk, vv in v.items() if kk != "factor"} for k, v in bt_results.items()}
    out_path.write_text(json.dumps({"period": PERIOD, "results": save_data}, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

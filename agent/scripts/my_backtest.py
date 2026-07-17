"""幸存4因子全回测 + GTJA主题扫描

用法:
    cd Vibe-Trading/agent
    python scripts/my_backtest.py

流程:
    1. 加载长周期 OHLCV panel
    2. 计算4个存活因子 + z-score等权合成
    3. 月频 top-N 回测
    4. GTJA 各主题 IC 扫描
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("my_backtest")

UNIVERSE = "all-a-share"
PERIOD = "2023-01-01/2026-07-10"
TOP_N = 20
INITIAL_CASH = 1_000_000

SURVIVOR_IDS = [
    "my_volume_volatility",
    "my_volume_ratio_reversal",
    "my_close_volume_cov",
    "my_high_volume_corr",
]


def _zscore(df: pd.DataFrame) -> pd.DataFrame:
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True).replace(0, np.nan)
    return df.sub(mean, axis=0).div(std, axis=0)


def main():
    t0 = time.time()
    log.info("=" * 60)
    log.info("  幸存4因子全回测 + GTJA 主题扫描")
    log.info("  Period: %s", PERIOD)
    log.info("=" * 60)

    from src.tools.alpha_bench_tool import _load_universe_panel
    from src.factors.registry import Registry

    # ── 1. Panel ──
    log.info("\n[1] 加载 OHLCV panel ...")
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    close = panel["close"]
    log.info("  %d days × %d stocks", close.shape[0], close.shape[1])

    registry = Registry()

    # ── 2. 幸存因子合成 ──
    log.info("\n[2] 幸存4因子合成 ...")
    signals = []
    for aid in SURVIVOR_IDS:
        tf = time.time()
        raw = registry.compute(aid, panel)
        z = _zscore(raw)
        signals.append(z)
        log.info("  %s: %.1fs", aid, time.time() - tf)

    composite = sum(signals) / len(signals)
    log.info("  Composite signal: %d days × %d stocks", composite.shape[0], composite.shape[1])

    # ── 3. 回测 ──
    log.info("\n[3] 回测 (月频 top-%d, 无卖空) ...", TOP_N)
    tf = time.time()

    # Find rebalance dates: last trading day of each month
    dates = composite.index
    monthly = dates[dates.to_period("M").duplicated(keep="last")]

    equity = []
    trades = []
    position: dict[str, float] = {}
    cash = INITIAL_CASH

    for i, reb_date in enumerate(monthly):
        if reb_date not in composite.index:
            continue

        sig = composite.loc[reb_date].dropna().sort_values(ascending=False)
        picks = sig.head(TOP_N).index.tolist()

        # Next trading day after reb_date
        next_dates = dates[dates > reb_date]
        if next_dates.empty:
            break
        exec_date = next_dates[0]
        prices = close.loc[exec_date]

        # Sell positions not in picks
        for code in list(position.keys()):
            if code not in picks and code in prices.index and not pd.isna(prices[code]):
                proceeds = position[code] * prices[code]
                cash += proceeds
                trades.append({
                    "date": str(exec_date.date()), "code": code,
                    "action": "sell", "shares": round(position[code], 2),
                    "price": float(prices[code]), "value": float(proceeds),
                })
                del position[code]

        # Buy new picks
        buy_list = [c for c in picks if c not in position and c in prices.index and not pd.isna(prices[c])]
        if buy_list:
            cash_per = cash / len(buy_list)
            for code in buy_list:
                shares = cash_per / prices[code]
                position[code] = shares
                trades.append({
                    "date": str(exec_date.date()), "code": code,
                    "action": "buy", "shares": round(shares, 2),
                    "price": float(prices[code]), "value": float(cash_per),
                })
            cash = 0.0

        # Mark to market
        mv = cash
        for code, shares in list(position.items()):
            if code in prices.index and not pd.isna(prices[code]):
                mv += shares * prices[code]
            else:
                del position[code]

        equity.append({
            "date": str(exec_date.date()),
            "value": round(float(mv), 2),
            "holdings": len(position),
        })

    log.info("  回测完成: %.1fs", time.time() - tf)

    # ── 4. 指标 ──
    log.info("\n[4] 绩效指标")
    equity_df = pd.DataFrame(equity)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    if equity_df.empty or len(equity_df) < 2:
        log.warning("  回测数据不足")
        return

    values = equity_df["value"].values
    total_ret = values[-1] / values[0] - 1
    n_periods = len(values)

    period_rets = pd.Series(values).pct_change().dropna().values
    sharpe = np.sqrt(12) * period_rets.mean() / period_rets.std() if period_rets.std() > 0 else 0

    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak
    max_dd = dd.min()
    win_rate = (period_rets > 0).mean()
    annual_ret = (1 + total_ret) ** (12 / n_periods) - 1 if n_periods > 0 else 0

    log.info("  Total Return      : %.1f%%", total_ret * 100)
    log.info("  Annual Return     : %.1f%%", annual_ret * 100)
    log.info("  Sharpe            : %.2f", sharpe)
    log.info("  Max Drawdown      : %.1f%%", max_dd * 100)
    log.info("  Win Rate          : %.0f%%", win_rate * 100)
    log.info("  Trades            : %d", len(trades_df))
    log.info("  Final Value       : %.0f", values[-1])

    # ── 5. GTJA 主题扫描 ──
    log.info("\n[5] GTJA 主题 IC 扫描 ...")
    tf2 = time.time()
    alpha_ids = registry.list(zoo="gtja191")
    forward_ret = close.pct_change().shift(-1)

    theme_ics: dict[str, list[float]] = defaultdict(list)
    for aid in alpha_ids:
        try:
            meta = registry.get(aid)
            factor = registry.compute(aid, panel)
        except Exception:
            continue

        theme = (meta.meta.get("theme") or ["unknown"])[0] if isinstance(meta.meta.get("theme"), list) else (meta.meta.get("theme") or "unknown")

        ic_vals = []
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
                ic_vals.append(ic)

        if len(ic_vals) >= 10:
            theme_ics[theme].extend(ic_vals)

    log.info("  GTJA 主题 IC 统计 (扫描 %d 个因子):", sum(len(v) for v in theme_ics.values()))
    log.info(f"  {'Theme':20s} {'Mean IC':>8s} {'IR':>8s} {'IC+%':>6s} {'N':>6s}")
    log.info("  " + "-" * 50)
    for theme in sorted(theme_ics.keys()):
        ic_arr = np.array(theme_ics[theme])
        mean_ic = ic_arr.mean()
        ir = mean_ic / ic_arr.std() if ic_arr.std() > 0 else 0
        pos_ratio = (ic_arr > 0).mean()
        log.info(f"  {theme:20s} {mean_ic:8.4f} {ir:8.4f} {pos_ratio:6.2f} {len(ic_arr):6d}")

    log.info("  GTJA 扫描耗时: %.0fs", time.time() - tf2)
    log.info("\n总耗时: %.0fs", time.time() - t0)

    # ── 6. 保存 ──
    out_dir = Path("output") / "my_backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    equity_df.to_csv(out_dir / "equity.csv", index=False)
    if not trades_df.empty:
        trades_df.to_csv(out_dir / "trades.csv", index=False)

    summary = {
        "period": PERIOD,
        "factors": SURVIVOR_IDS,
        "total_return_pct": round(total_ret * 100, 1),
        "annual_return_pct": round(annual_ret * 100, 1),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 1),
        "win_rate_pct": round(win_rate * 100, 0),
        "n_trades": len(trades_df),
        "final_value": round(values[-1], 0),
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    log.info("已保存到 %s", out_dir)


if __name__ == "__main__":
    main()

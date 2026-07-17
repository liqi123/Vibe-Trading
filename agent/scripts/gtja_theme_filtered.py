"""GTJA191 主题分层 + IC 过滤 + 滚动窗口回测

滚动逻辑: 每 6 个月用过去 252 个交易日重算 IC → 重新筛选存活因子 →
重新构建主题组合。因子值只算一次，IC 在每个窗口切片计算。

Usage:
    cd Vibe-Trading/agent
    python scripts/gtja_theme_filtered.py
"""
import json
import logging
import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gtja_roll")
def info(msg, *args):
    log.info(msg, *args)


UNIVERSE = "all-a-share"
FULL_PERIOD = "2022-01-01/2024-12-31"
TOP_N = 20
INITIAL_CASH = 1_000_000
IC_WINDOW = 252       # 训练窗口: ~252个交易日
ROLL_STEP = 126       # 每126个交易日 (~6个月) 重算一次

THEME_RENAME = {
    "momentum,volume": "momentum",
    "volume,momentum": "volume",
    "volume,microstructure": "volume",
    "volatility,volume": "volatility",
    "volume,reversal": "volume",
    "volume,volatility": "volume",
    "reversal,microstructure": "reversal",
    "volatility,reversal": "volatility",
    "momentum,microstructure": "momentum",
    "volatility,microstructure": "volatility",
    "sentiment,momentum": "momentum",
    "reversal,volume": "reversal",
}


def primary_theme(raw):
    t = raw[0] if isinstance(raw, list) else raw
    return THEME_RENAME.get(t, t)


def _zscore_cross_section(df):
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    std = std.where(std > 1e-12)
    return df.sub(mean, axis=0).div(std, axis=0)


def _nanmean_df(arrays):
    ref = arrays[0]
    total = pd.DataFrame(0.0, index=ref.index, columns=ref.columns)
    cnt = pd.DataFrame(0, index=ref.index, columns=ref.columns)
    for df in arrays:
        mask = df.notna()
        total += df.fillna(0.0)
        cnt += mask.astype(int)
    return total / cnt.replace(0, np.nan)


def compute_ic_series(factor, fwd_ret):
    aligned = factor.reindex_like(fwd_ret)
    ic = aligned.corrwith(fwd_ret, axis=1, method="spearman")
    return ic.dropna()


def categorise(ic_mean, ic_std, ic_pos, n):
    if not (n > 0 and ic_std > 0):
        return "dead"
    t = ic_mean / (ic_std / math.sqrt(n))
    if ic_mean > 0.02 and ic_pos >= 0.55 and abs(t) > 2:
        return "alive"
    if ic_mean < -0.02 and abs(t) > 2:
        return "reversed"
    return "dead"


def main():
    start = time.time()
    info("=" * 60)
    info("  GTJA191 滚动窗口回测（主题分层 + IC 过滤）")
    info("  IC窗口: %d天  滚动步长: %d天", IC_WINDOW, ROLL_STEP)
    info("=" * 60)
    info("")

    # ── 1. 加载数据 ──
    from src.tools.alpha_bench_tool import _load_universe_panel
    info("Loading panel...")
    panel = _load_universe_panel(UNIVERSE, FULL_PERIOD)
    close = panel["close"]
    info("  %d days × %d stocks", close.shape[0], close.shape[1])

    from src.factors.registry import Registry
    registry = Registry()
    alpha_ids = registry.list(zoo="gtja191")

    # ── 2. 确定主题 ──
    theme_map = {}
    for aid in alpha_ids:
        a = registry.get(aid)
        t = a.meta.get("theme", ["uncategorised"])
        theme_map[aid] = primary_theme(t)

    info("\n%d alphas across %d themes",
         len(alpha_ids), len(set(theme_map.values())))

    # ── 3. 一次性计算所有因子（全时段）──
    info("\nComputing all factors once...")
    t0 = time.time()
    factor_cache = {}  # alpha_id -> DataFrame (full period)
    for aid in alpha_ids:
        try:
            raw = registry.compute(aid, panel)
            z = _zscore_cross_section(raw)
            factor_cache[aid] = z
        except Exception:
            continue
    info("  Cached %d/%d factors in %.0fs",
         len(factor_cache), len(alpha_ids), time.time() - t0)

    # ── 4. 滚动窗口 ──
    all_dates = close.index
    roll_starts = range(IC_WINDOW, len(all_dates), ROLL_STEP)
    info("\nRolling windows: %d", len(roll_starts))
    info("  %-16s %-16s  %s", "Train end", "Test period", "Alive/total")

    # Storage for all trading signals
    all_signal_parts = []

    for wi, train_end_idx in enumerate(roll_starts):
        train_start_idx = train_end_idx - IC_WINDOW
        train_end = all_dates[train_end_idx - 1]
        test_start = all_dates[train_end_idx]
        test_end_idx = min(train_end_idx + ROLL_STEP, len(all_dates))
        test_end = all_dates[test_end_idx - 1]
        test_slice = slice(train_end_idx, test_end_idx)

        train_dates = all_dates[train_start_idx:train_end_idx]
        test_dates = all_dates[test_slice]

        # Compute IC on training window
        train_close = close.loc[train_dates]
        fwd_ret = train_close.pct_change().shift(-1)

        theme_results = defaultdict(list)
        for aid, z_full in factor_cache.items():
            z_train = z_full.reindex(train_dates).dropna(how="all")
            if z_train.empty:
                continue
            ic_series = compute_ic_series(z_train, fwd_ret).dropna()
            if len(ic_series) < 5:
                continue
            ic_mean = float(ic_series.mean())
            ic_std = float(ic_series.std())
            ic_pos = float((ic_series > 0).mean())
            n = len(ic_series)
            cat = categorise(ic_mean, ic_std, ic_pos, n)
            theme_results[theme_map[aid]].append({
                "id": aid, "ic_mean": ic_mean, "cat": cat,
            })

        # Build theme composites for this window
        theme_signals = {}
        total_alive = 0
        for theme, rows in theme_results.items():
            alive = [r["id"] for r in rows if r["cat"] == "alive"]
            if not alive:
                continue
            signals = []
            for aid in alive:
                z_test = factor_cache[aid].reindex(test_dates)
                if z_test.isna().all().all():
                    continue
                signals.append(z_test)
            if signals:
                theme_signals[theme] = _nanmean_df(signals)
                total_alive += len(alive)

        if not theme_signals:
            continue

        # Final signal for this window: equal-weight themes
        window_signal = sum(theme_signals.values()) / len(theme_signals)
        all_signal_parts.append(window_signal)

        info("  %-16s %-16s  %d/%d",
             str(train_end.date()), f"{test_start.date()}~{test_end.date()}",
             total_alive, len(factor_cache))

    # ── 5. 拼接全时段信号 ──
    if not all_signal_parts:
        info("No signals produced")
        return

    final_signal = pd.concat(all_signal_parts).sort_index()
    # Remove duplicate indices (edges of windows)
    final_signal = final_signal[~final_signal.index.duplicated(keep="first")]
    info("\nFinal signal: %d days", final_signal.shape[0])

    # ── 6. 回测 ──
    info("\nRunning backtest (top-%d, monthly rebalance)...", TOP_N)
    t0 = time.time()

    dates = final_signal.index
    periods = dates.to_period("M")
    equity = []
    trades = []
    position = {}
    current_cash = INITIAL_CASH

    for period_label, grp in final_signal.groupby(periods):
        sig_date = grp.index[-1]
        next_dates = close.index[close.index > sig_date]
        if len(next_dates) == 0:
            break
        next_date = next_dates[0]
        prices = close.loc[next_date]

        ranked = grp.loc[sig_date].dropna().sort_values(ascending=False)
        picks = ranked.head(TOP_N).index.tolist()

        for code in list(position.keys()):
            if code not in picks and code in prices.index and not pd.isna(prices[code]):
                proceeds = position[code] * prices[code]
                current_cash += proceeds
                trades.append({
                    "date": str(next_date.date()), "code": code,
                    "action": "sell", "shares": position[code],
                    "price": float(prices[code]), "value": float(proceeds),
                })
                del position[code]

        buy_list = [c for c in picks if c not in position and c in prices.index and not pd.isna(prices[c])]
        if buy_list:
            cash_per = current_cash / len(buy_list)
            for code in buy_list:
                shares = cash_per / prices[code]
                position[code] = shares
                trades.append({
                    "date": str(next_date.date()), "code": code,
                    "action": "buy", "shares": round(shares, 2),
                    "price": float(prices[code]), "value": float(cash_per),
                })
            current_cash = 0.0

        mv = current_cash
        for code, shares in list(position.items()):
            if code in prices.index and not pd.isna(prices[code]):
                mv += shares * prices[code]
            else:
                del position[code]

        equity.append({
            "date": str(next_date.date()),
            "value": round(float(mv), 2),
            "holdings": len(position),
        })

    info("  done in %.1fs", time.time() - t0)

    # ── 7. 指标 ──
    equity_df = pd.DataFrame(equity)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    if equity_df.empty or len(equity_df) < 2:
        info("Not enough data")
        return

    values = equity_df["value"].values
    total_ret = values[-1] / values[0] - 1
    n_p = len(values)
    annual_ret = (1 + total_ret) ** (12 / n_p) - 1 if n_p > 0 else 0

    monthly_rets = pd.Series(values).pct_change().dropna().values
    sharpe = np.sqrt(12) * monthly_rets.mean() / monthly_rets.std() if monthly_rets.std() > 0 else 0

    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak
    max_dd = dd.min()
    win_rate = (monthly_rets > 0).mean()

    info("")
    info("-" * 60)
    info("  滚动回测结果")
    info("-" * 60)
    info("  IC窗口: %d天, 滚动步长: %d天", IC_WINDOW, ROLL_STEP)
    info("  调仓: 月度 top-%d", TOP_N)
    info("")
    info("  Total Return      : %.1f%%", total_ret * 100)
    info("  Annual Return     : %.1f%%", annual_ret * 100)
    info("  Sharpe            : %.2f", sharpe)
    info("  Max Drawdown      : %.1f%%", max_dd * 100)
    info("  Win Rate          : %.0f%%", win_rate * 100)
    info("  Trades            : %d", len(trades_df))
    info("  Final Value       : %.0f", values[-1])
    info("")
    info("  Time elapsed: %.0fs (%.0f min)",
         time.time() - start, (time.time() - start) / 60)

    # ── 8. 保存 ──
    out_dir = Path(__file__).parent.parent / "output" / "gtja_rolling"
    out_dir.mkdir(parents=True, exist_ok=True)
    equity_df.to_csv(out_dir / "equity.csv", index=False)
    if not trades_df.empty:
        trades_df.to_csv(out_dir / "trades.csv", index=False)

    summary = {
        "total_return": f"{total_ret*100:.1f}%",
        "annual_return": f"{annual_ret*100:.1f}%",
        "sharpe": round(sharpe, 2),
        "max_drawdown": f"{max_dd*100:.1f}%",
        "win_rate": f"{win_rate*100:.0f}%",
        "n_trades": len(trades_df),
        "final_value": f"{values[-1]:.0f}",
        "ic_window": IC_WINDOW,
        "roll_step": ROLL_STEP,
    }
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    info("Results saved to %s", out_dir)


if __name__ == "__main__":
    main()

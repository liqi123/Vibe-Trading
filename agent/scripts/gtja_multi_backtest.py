"""GTJA191 全因子主题分组合成回测

思路：191个因子不扔掉任何一个，按 theme 分组 → 组内 z-score 等权合成 →
各主题复合信号等权合成 → 月频 top-N 多头。

Usage:
    cd Vibe-Trading/agent
    python scripts/gtja_multi_backtest.py
"""
import json
import logging
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gtja_multi")
def info(msg, *args):
    log.info(msg, *args)


PERIOD = "2024-01-01/2024-12-31"
UNIVERSE = "all-a-share"
TOP_N = 20
REBALANCE_FREQ = "M"
INITIAL_CASH = 1_000_000


def load_panel(universe, period):
    from src.tools.alpha_bench_tool import _load_universe_panel
    info("Loading panel %s %s ...", universe, period)
    t0 = time.time()
    panel = _load_universe_panel(universe, period)
    info("  done in %.0fs  stocks=%d  days=%d",
        time.time() - t0,
        panel["close"].shape[1],
        panel["close"].shape[0])
    return panel


def get_registry():
    from src.factors.registry import Registry
    return Registry()


def _zscore_cross_section(df):
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    std = std.where(std > 1e-12)
    return df.sub(mean, axis=0).div(std, axis=0)


def get_alpha_themes(registry):
    """Get theme mapping for all GTJA191 alphas."""
    alpha_ids = registry.list(zoo="gtja191")
    themes = {}
    for aid in alpha_ids:
        try:
            alpha = registry.get(aid)
            t = alpha.meta.get("theme", ["uncategorised"])
            themes[aid] = t[0] if isinstance(t, list) else t
        except Exception:
            themes[aid] = "uncategorised"
    return themes


def _nanmean(arrays):
    """Element-wise mean ignoring NaN. Memory-safe: iterates, no stacking."""
    ref = arrays[0]
    total = pd.DataFrame(0.0, index=ref.index, columns=ref.columns)
    count = pd.DataFrame(0, index=ref.index, columns=ref.columns)
    for df in arrays:
        mask = df.notna()
        total += df.fillna(0.0)
        count += mask.astype(int)
    return total / count.replace(0, np.nan)


def compute_theme_composites(panel, registry, theme_map):
    """Compute one composite signal per theme.

    group by theme → within-theme z-score → nanmean theme composite
    """
    theme_groups = defaultdict(list)
    for aid, theme in theme_map.items():
        theme_groups[theme].append(aid)

    info("Computing all %d GTJA191 factors grouped into %d themes...",
         len(theme_map), len(theme_groups))
    t0 = time.time()

    n_skipped = 0
    theme_composites = {}
    for theme, aids in sorted(theme_groups.items()):
        info("\n  [%s] %d factors...", theme, len(aids))
        signals = []
        for aid in aids:
            try:
                raw = registry.compute(aid, panel)
                z = _zscore_cross_section(raw)
                signals.append(z)
            except Exception:
                n_skipped += 1
                continue

        if signals:
            composite = _nanmean(signals)
            theme_composites[theme] = composite
            info("    → done: %s composite (%.0f%% coverage)",
                 theme, composite.iloc[-1].notna().mean() * 100)

    info("\nAll themes done in %.0fs (%d skipped)", time.time() - t0, n_skipped)
    return theme_composites


def run_backtest(signal, close_panel, freq="M", top_n=20, cash=1_000_000):
    """Monthly rebalance backtest."""
    dates = signal.index
    periods = dates.to_period(freq)
    equity = []
    trades = []
    position = {}
    current_cash = cash

    for period_label, grp in signal.groupby(periods):
        sig_date = grp.index[-1]
        next_dates = close_panel.index[close_panel.index > sig_date]
        if len(next_dates) == 0:
            break
        next_date = next_dates[0]
        prices = close_panel.loc[next_date]

        ranked = grp.loc[sig_date].dropna().sort_values(ascending=False)
        picks = ranked.head(top_n).index.tolist()

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

    return pd.DataFrame(equity), pd.DataFrame(trades)


def calc_metrics(equity_df, trades_df):
    if equity_df.empty or len(equity_df) < 2:
        return {"error": "not enough data"}

    values = equity_df["value"].values
    total_ret = values[-1] / values[0] - 1
    n_periods = len(values)
    annual_ret = (1 + total_ret) ** (12 / n_periods) - 1 if n_periods > 0 else 0

    monthly_rets = pd.Series(values).pct_change().dropna().values
    sharpe = np.sqrt(12) * monthly_rets.mean() / monthly_rets.std() if monthly_rets.std() > 0 else 0

    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak
    max_dd = dd.min()
    win_rate = (monthly_rets > 0).mean()

    return {
        "total_return": f"{total_ret*100:.1f}%",
        "annual_return": f"{annual_ret*100:.1f}%",
        "sharpe": f"{sharpe:.2f}",
        "max_drawdown": f"{max_dd*100:.1f}%",
        "win_rate": f"{win_rate*100:.0f}%",
        "n_trades": len(trades_df) if not trades_df.empty else 0,
        "n_periods": n_periods,
        "final_value": f"{values[-1]:.0f}",
    }


def print_theme_breakdown(theme_composites, theme_map):
    info("")
    info("  Theme breakdown:")
    info("  %-22s %4s  %s", "Theme", "N", "Composite shape")
    info("  " + "-" * 50)
    for theme, comp in sorted(theme_composites.items()):
        n_factors = sum(1 for t in theme_map.values() if t == theme)
        info("  %-22s %4d  %s", theme, n_factors, str(comp.shape))


def main():
    start = time.time()
    info("=" * 55)
    info("  GTJA191 全因子主题分组回测")
    info("=" * 55)
    info("")

    panel = load_panel(UNIVERSE, PERIOD)
    registry = get_registry()
    theme_map = get_alpha_themes(registry)

    info("GTJA191: %d alphas, themes: %s",
         len(theme_map), sorted(set(theme_map.values())))

    theme_composites = compute_theme_composites(panel, registry, theme_map)
    print_theme_breakdown(theme_composites, theme_map)

    # Final signal: equal-weight theme composites
    info("\nCombining %d theme composites...", len(theme_composites))
    final_signal = sum(theme_composites.values()) / len(theme_composites)

    info("\nRunning backtest (top-%d, monthly rebalance)...", TOP_N)
    t0 = time.time()
    equity_df, trades_df = run_backtest(
        final_signal, panel["close"], freq=REBALANCE_FREQ,
        top_n=TOP_N, cash=INITIAL_CASH
    )
    info("  done in %.1fs", time.time() - t0)

    metrics = calc_metrics(equity_df, trades_df)

    info("")
    info("-" * 55)
    info("  回测结果")
    info("-" * 55)
    info("  策略: GTJA191 全因子主题分组合成 (top-%d)", TOP_N)
    info("  期间: %s", PERIOD)
    info("  调仓: 月度")
    info("")
    info("  Total Return    : %s", metrics.get("total_return", "N/A"))
    info("  Annual Return   : %s", metrics.get("annual_return", "N/A"))
    info("  Sharpe          : %s", metrics.get("sharpe", "N/A"))
    info("  Max Drawdown    : %s", metrics.get("max_drawdown", "N/A"))
    info("  Win Rate        : %s", metrics.get("win_rate", "N/A"))
    info("  Trades          : %s", metrics.get("n_trades", "N/A"))
    info("  Final Value     : %s", metrics.get("final_value", "N/A"))
    info("")
    info("  Time elapsed: %.0fs", time.time() - start)

    out_dir = Path(__file__).parent.parent / "output" / "gtja_multi_theme"
    out_dir.mkdir(parents=True, exist_ok=True)
    equity_df.to_csv(out_dir / "equity.csv", index=False)
    if not trades_df.empty:
        trades_df.to_csv(out_dir / "trades.csv", index=False)
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    with open(out_dir / "theme_map.json", "w") as f:
        json.dump(theme_map, f, indent=2, ensure_ascii=False)
    info("\nResults saved to %s", out_dir)


if __name__ == "__main__":
    main()

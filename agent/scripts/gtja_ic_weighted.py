"""GTJA191 IC 加权合成回测

思路：191个因子各自算 IC → IC 作为权重 → 截面 z-score 后 IC 加权合成 → 月频 top-N。

训练期（2024-01~06）算 IC 权重 → 测试期（2024-07~12）跑回测，避免前视偏差。

Usage:
    cd Vibe-Trading/agent
    python scripts/gtja_ic_weighted.py
"""
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gtja_ic")
def info(msg, *args):
    log.info(msg, *args)


UNIVERSE = "all-a-share"
FULL_PERIOD = "2024-01-01/2024-12-31"
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


def compute_forward_returns(close):
    """Next-bar simple forward returns aligned to current row."""
    return close.pct_change().shift(-1)


def compute_ic_series(factor, fwd_ret):
    """Cross-sectional Spearman rank IC per date."""
    aligned_f = factor.reindex_like(fwd_ret)
    ic = aligned_f.corrwith(fwd_ret, axis=1, method="spearman")
    return ic.dropna()


def main():
    start = time.time()
    info("=" * 55)
    info("  GTJA191 IC 加权合成回测（训练/测试分离）")
    info("=" * 55)
    info("")

    # 1. Load full year panel and slice train/test
    panel_full = load_panel(UNIVERSE, FULL_PERIOD)
    close_all = panel_full["close"]

    # Split by date
    train_end = "2024-06-30"
    train_mask = close_all.index <= train_end
    test_mask = close_all.index > train_end

    panel_train = {k: v.loc[train_mask] for k, v in panel_full.items()}
    panel_test = {k: v.loc[test_mask] for k, v in panel_full.items()}

    TRAIN_LABEL = f"2024-01-01/{train_end}"
    TEST_LABEL = f"2024-07-01/2024-12-31"

    info("\nTrain: %s  (%d days)", TRAIN_LABEL, panel_train["close"].shape[0])
    info("Test:  %s  (%d days)", TEST_LABEL, panel_test["close"].shape[0])

    registry = get_registry()

    # 2. Get all GTJA191 alpha IDs
    alpha_ids = registry.list(zoo="gtja191")
    info("\nGTJA191: %d alphas", len(alpha_ids))

    # 3. Compute IC weights on training period
    fwd_ret = compute_forward_returns(panel_train["close"])

    info("\nComputing IC weights (training: %s)...", TRAIN_LABEL)
    ic_weights = {}
    t0 = time.time()
    n_ok = 0

    for aid in alpha_ids:
        try:
            raw = registry.compute(aid, panel_train)
            z = _zscore_cross_section(raw)
            ic_series = compute_ic_series(z, fwd_ret)
            ic_mean = ic_series.mean()
            if not np.isnan(ic_mean):
                ic_weights[aid] = ic_mean
                n_ok += 1
        except Exception:
            continue

    info("  IC computed for %d/%d alphas in %.0fs",
         n_ok, len(alpha_ids), time.time() - t0)

    # IC distribution
    ics = np.array(list(ic_weights.values()))
    info("\n  IC stats:")
    info("    Mean:    %.4f", ics.mean())
    info("    Std:     %.4f", ics.std())
    info("    Median:  %.4f", np.median(ics))
    info("    > 0:     %d (%.0f%%)", (ics > 0).sum(), (ics > 0).mean() * 100)
    info("    > 0.02:  %d", (ics > 0.02).sum())
    info("    < -0.02: %d", (ics < -0.02).sum())

    # Use max(IC, 0) as weight (negative IC → 0 = skip)
    for aid in ic_weights:
        ic_weights[aid] = max(ic_weights[aid], 0.0)
    total_w = sum(ic_weights.values())
    if total_w > 0:
        for aid in ic_weights:
            ic_weights[aid] /= total_w  # normalize

    n_nonzero = sum(1 for v in ic_weights.values() if v > 0)
    info("\n  Non-zero weights: %d / %d", n_nonzero, len(ic_weights))
    top_weights = sorted(ic_weights.items(), key=lambda x: -x[1])[:10]
    info("  Top 10 by IC weight:")
    for aid, w in top_weights:
        info("    %s: weight=%.4f", aid, w)

    # 4. Compute composite on test period
    info("\nComputing IC-weighted composite (test: %s)...", TEST_LABEL)
    t0 = time.time()

    # Build composite incrementally to avoid memory blowup
    ref = panel_test["close"]
    composite = pd.DataFrame(0.0, index=ref.index, columns=ref.columns)
    n_alive = 0
    for aid, w in ic_weights.items():
        if w <= 0:
            continue
        try:
            raw = registry.compute(aid, panel_test)
            z = _zscore_cross_section(raw)
            composite += z.multiply(w)
            n_alive += 1
        except Exception:
            continue

    info("  Composite built from %d factors in %.0fs  shape=%s",
         n_alive, time.time() - t0, composite.shape)

    # 5. Run backtest on test period
    info("\nRunning backtest (top-%d, monthly rebalance)...", TOP_N)
    t0 = time.time()

    # --- Backtest ---
    dates = composite.index
    periods = dates.to_period(REBALANCE_FREQ)
    equity = []
    trades = []
    position = {}
    current_cash = INITIAL_CASH
    close = panel_test["close"]

    for period_label, grp in composite.groupby(periods):
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

    # 6. Metrics
    equity_df = pd.DataFrame(equity)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    if equity_df.empty or len(equity_df) < 2:
        info("Not enough data")
        return

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

    info("")
    info("-" * 55)
    info("  回测结果（测试期）")
    info("-" * 55)
    info("  方法: IC 加权合成 (训练 IC → 权重)")
    info("  训练: %s", TRAIN_LABEL)
    info("  测试: %s", TEST_LABEL)
    info("  有效因子: %d / %d", n_alive, len(alpha_ids))
    info("  调仓: 月度 top-%d", TOP_N)
    info("")
    info("  Total Return    : %.1f%%", total_ret * 100)
    info("  Annual Return   : %.1f%%", annual_ret * 100)
    info("  Sharpe          : %.2f", sharpe)
    info("  Max Drawdown    : %.1f%%", max_dd * 100)
    info("  Win Rate        : %.0f%%", win_rate * 100)
    info("  Trades          : %d", len(trades_df))
    info("  Final Value     : %.0f", values[-1])
    info("")
    info("  Time elapsed: %.0fs", time.time() - start)

    # 7. Save
    out_dir = Path(__file__).parent.parent / "output" / "gtja_ic_weighted"
    out_dir.mkdir(parents=True, exist_ok=True)
    equity_df.to_csv(out_dir / "equity.csv", index=False)
    if not trades_df.empty:
        trades_df.to_csv(out_dir / "trades.csv", index=False)

    # Save IC weights
    ic_sorted = sorted(ic_weights.items(), key=lambda x: -x[1])
    with open(out_dir / "ic_weights.json", "w") as f:
        json.dump({k: round(v, 6) for k, v in ic_sorted if v > 0},
                  f, indent=2, ensure_ascii=False)

    metrics = {
        "total_return": f"{total_ret*100:.1f}%",
        "annual_return": f"{annual_ret*100:.1f}%",
        "sharpe": round(sharpe, 2),
        "max_drawdown": f"{max_dd*100:.1f}%",
        "win_rate": f"{win_rate*100:.0f}%",
        "n_trades": len(trades_df),
        "final_value": f"{values[-1]:.0f}",
        "train_period": TRAIN_LABEL,
        "test_period": TEST_LABEL,
        "n_factors_total": len(alpha_ids),
        "n_factors_effective": n_alive,
    }
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    info("Results saved to %s", out_dir)


if __name__ == "__main__":
    main()

"""14因子 vs 16因子 IC对比"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("compare")

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


def main():
    from strategies.composite.composite_14factor import compute_14factor
    from strategies.composite.composite_16factor import compute_16factor
    from strategies.composite.composite_16factor_v2 import compute_16factor_v2

    t0 = time.time()
    log.info("=" * 80)
    log.info("14因子 vs 16因子 IC对比")
    log.info("Period: %s", PERIOD)
    log.info("=" * 80)

    # ── 1. 加载 panel ──
    log.info("\n[1/3] 加载 OHLCV panel ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    close = panel["close"]
    n_stocks = close.shape[1]
    n_days = close.shape[0]
    log.info("  OHLCV 就绪: %d 只 × %d 日", n_stocks, n_days)

    # ── 2. 叠加问财数据 ──
    log.info("\n[2/3] 叠加问财数据（从DB加载）...")
    try:
        import sqlite3
        db_path = r"G:\tdx_data\tdx_daily.db"
        conn = sqlite3.connect(db_path, timeout=10)
        dates = [d.strftime("%Y-%m-%d") for d in close.index]
        fields = ["turnover_pct", "pe_ttm", "pb", "mcap_yi", "main_net_flow", "margin_balance"]
        placeholders = ",".join(["?"] * len(dates))
        rows = conn.execute(
            f"SELECT date, code, {','.join(fields)} FROM fund_daily WHERE date IN ({placeholders})",
            dates
        ).fetchall()
        conn.close()
        if rows:
            df = pd.DataFrame(rows, columns=["date", "code"] + fields)
            code_map = {col.split(".")[0]: col for col in close.columns}
            df["code_full"] = df["code"].map(code_map)
            df = df.dropna(subset=["code_full"])
            for fld in fields:
                pivot = df.pivot(index="date", columns="code_full", values=fld)
                pivot.index = pd.DatetimeIndex(pivot.index)
                panel[f"fund:{fld}"] = pivot.reindex(close.index).reindex(columns=close.columns)
            log.info("  从DB加载完成: %d 条记录", len(rows))
    except Exception as exc:
        log.warning("加载失败: %s", exc)

    # ── 3. 计算因子并对比 ──
    log.info("\n[3/3] 计算因子并对比 ...")
    forward_ret = close.pct_change(periods=1).shift(-1)

    results = []

    for name, compute_fn in [("14-Factor", compute_14factor), ("16-Factor", compute_16factor), ("16-Factor v2", compute_16factor_v2)]:
        log.info("  计算 %s ...", name)
        tf = time.time()
        try:
            factor_df = compute_fn(panel)
        except Exception as exc:
            log.warning("  compute failed: %s", exc)
            continue
        compute_t = time.time() - tf

        nan_pct = factor_df.isna().sum().sum() / (factor_df.shape[0] * factor_df.shape[1]) * 100
        log.info("    compute: %.2fs  NaN ratio: %.1f%%", compute_t, nan_pct)

        ic_series = _compute_ic_series(factor_df, forward_ret)
        if ic_series.empty:
            log.warning("  IC series empty")
            continue

        ic_mean = ic_series.mean()
        ic_std = ic_series.std(ddof=1)
        ir = ic_mean / ic_std if ic_std > 0 else 0.0
        ic_pos_ratio = (ic_series > 0).mean()
        n = len(ic_series)
        t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 0 else 0.0

        # 按年份分段
        yearly = {}
        for yr in [2025, 2026]:
            yr_mask = ic_series.index.year == yr
            yr_ic = ic_series[yr_mask]
            if len(yr_ic) > 5:
                yearly[yr] = {
                    "ic": round(yr_ic.mean(), 4),
                    "ir": round(yr_ic.mean() / yr_ic.std() if yr_ic.std() > 0 else 0, 4),
                    "n": len(yr_ic),
                }

        results.append({
            "name": name,
            "n_days": n,
            "ic_mean": round(ic_mean, 4),
            "ir": round(ir, 4),
            "ic_pos_ratio": round(ic_pos_ratio, 4),
            "t_stat": round(t_stat, 2),
            "yearly": yearly,
        })

        status = "✅" if abs(t_stat) > 2 and ic_pos_ratio >= 0.55 else " "
        log.info("    %s IC=%.4f  IR=%.4f  IC+ratio=%.2f  t=%.2f  n=%d",
                 status, ic_mean, ir, ic_pos_ratio, t_stat, n)
        for yr, yd in sorted(yearly.items()):
            log.info("      %d: IC=%.4f IR=%.4f n=%d", yr, yd["ic"], yd["ir"], yd["n"])

    # ── 报告 ──
    log.info("\n" + "=" * 80)
    log.info("对比结果")
    log.info("=" * 80)
    log.info(f"{'Strategy':16s} {'IC_mean':>8s} {'IR':>8s} {'IC+%':>6s} {'t':>6s} {'n':>5s}")
    log.info("-" * 80)
    for r in results:
        log.info(f"{r['name']:16s} {r['ic_mean']:8.4f} {r['ir']:8.4f} "
                 f"{r['ic_pos_ratio']:6.2f} {r['t_stat']:6.2f} {r['n_days']:5d}")
        if r.get("yearly"):
            parts = []
            for yr in sorted(r["yearly"]):
                yd = r["yearly"][yr]
                parts.append(f"{yr}:IC={yd['ic']:.4f}")
            log.info(f"{'':16s}   年度: {', '.join(parts)}")

    # 提升幅度
    if len(results) == 2:
        r14, r16 = results[0], results[1]
        ic_lift = (r16["ic_mean"] - r14["ic_mean"]) / abs(r14["ic_mean"]) * 100 if r14["ic_mean"] != 0 else 0
        ir_lift = (r16["ir"] - r14["ir"]) / abs(r14["ir"]) * 100 if r14["ir"] != 0 else 0
        log.info("-" * 80)
        log.info("16因子 vs 14因子提升:")
        log.info("  IC提升: %.1f%%  IR提升: %.1f%%", ic_lift, ir_lift)

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)


if __name__ == "__main__":
    main()

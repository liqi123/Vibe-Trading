"""快速因子 bench — 跳过慢速残差因子"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("bench_fast")

UNIVERSE = "all-a-share"
PERIOD = "2025-01-02/2026-07-10"

# 只测试快速因子（跳过residual_flow）
ALPHA_IDS = [
    "my_cap_neutral_turnover_v2",
    "my_composite_small_value_v2",
    "my_flow_turnover_interaction_v2",
    "my_main_flow_v2",
    "my_v2_composite",
]


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
    from src.factors.registry import Registry

    t0 = time.time()
    log.info("=" * 80)
    log.info("快速因子 bench (跳过残差因子)")
    log.info("Universe: %s  Period: %s", UNIVERSE, PERIOD)
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
        else:
            log.warning("  DB中无数据")
    except Exception as exc:
        log.warning("加载失败: %s", exc)

    log.info("  Panel 最终: %d 只 × %d 日", n_stocks, n_days)

    # ── 3. 计算因子 ──
    log.info("\n[3/3] 计算因子 ...")
    forward_ret = close.pct_change(periods=1).shift(-1)

    registry = Registry()
    results = []

    for alpha_id in ALPHA_IDS:
        try:
            meta = registry.get(alpha_id)
        except KeyError:
            log.warning("  alpha %s 未找到", alpha_id)
            continue

        nickname = meta.meta.get("nickname", "")
        log.info("  %s ...", alpha_id)
        if nickname:
            log.info("    %s", nickname)

        tf = time.time()
        try:
            factor_df = registry.compute(alpha_id, panel)
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

        # 按年份分段统计
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
            "alpha_id": alpha_id,
            "nickname": nickname,
            "n_days": n,
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(ic_std, 4),
            "ir": round(ir, 4),
            "ic_pos_ratio": round(ic_pos_ratio, 4),
            "t_stat": round(t_stat, 2),
            "compute_seconds": round(compute_t, 2),
            "nan_ratio_pct": round(nan_pct, 1),
            "yearly": yearly,
        })

        status = "✅" if abs(t_stat) > 2 and ic_pos_ratio >= 0.55 else " "
        log.info("    %s IC=%.4f  IR=%.4f  IC+ratio=%.2f  t=%.2f  n=%d",
                 status, ic_mean, ir, ic_pos_ratio, t_stat, n)
        for yr, yd in sorted(yearly.items()):
            log.info("      %d: IC=%.4f IR=%.4f n=%d", yr, yd["ic"], yd["ir"], yd["n"])

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("结果汇总")
    log.info("=" * 100)
    log.info(f"{'Alpha':32s} {'IC_mean':>8s} {'IR':>8s} {'IC+%':>6s} {'t':>6s} {'n':>5s} {'NaN%':>6s} {'Status'}")
    log.info("-" * 100)
    results.sort(key=lambda r: r["ir"], reverse=True)
    for r in results:
        status = "✅" if abs(r["t_stat"]) > 2 and r["ic_pos_ratio"] >= 0.55 else " "
        log.info(f"{r['alpha_id']:32s} {r['ic_mean']:8.4f} {r['ir']:8.4f} "
                 f"{r['ic_pos_ratio']:6.2f} {r['t_stat']:6.2f} {r['n_days']:5d} "
                 f"{r['nan_ratio_pct']:6.1f} {status}")
        if r.get("yearly"):
            parts = []
            for yr in sorted(r["yearly"]):
                yd = r["yearly"][yr]
                parts.append(f"{yr}:IC={yd['ic']:.4f},IR={yd['ir']:.4f}")
            log.info(f"{'':32s}   年度: {', '.join(parts)}")

    elapsed = time.time() - t0
    log.info("-" * 100)
    log.info("总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "bench_fast"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "metrics.json"
    out_path.write_text(json.dumps({
        "universe": UNIVERSE,
        "period": PERIOD,
        "n_stocks": n_stocks,
        "n_days": n_days,
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

"""另类数据因子 bench v2 — 测试优化后的因子"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("alt_bench_v2")

UNIVERSE = "all-a-share"
PERIOD = "2026-04-01/2026-07-10"

# 原版因子
ALPHA_IDS_ORIG = [
    "my_pe_value",
    "my_cap_neutral_turnover",
    "my_composite_small_value",
    "my_main_flow",
    "my_margin_sentiment",
    "my_flow_turnover_interaction",
]

# 优化版因子
ALPHA_IDS_V2 = [
    "my_pe_value_v2",
    "my_cap_neutral_turnover_v2",
    "my_composite_small_value_v2",
    "my_main_flow_v2",
    "my_margin_sentiment_v2",
    "my_flow_turnover_interaction_v2",
    "my_residual_flow",  # 保留已通过的
    "my_cap_neutral_turnover_v3",
    "my_main_flow_v3",
    "my_multi_signal_composite",
]


def _compute_ic_series(
    factor: pd.DataFrame,
    forward_ret: pd.DataFrame,
) -> pd.Series:
    """逐日 Spearman rank IC."""
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
    from scripts.alt_data_loader import load_iwencai_panel, load_auction_panel

    t0 = time.time()
    log.info("=" * 80)
    log.info("另类数据因子 bench v2 — 优化因子对比")
    log.info("Universe: %s  Period: %s", UNIVERSE, PERIOD)
    log.info("=" * 80)

    # ── 1. 加载 panel ──
    log.info("\n[1/4] 加载 OHLCV panel ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    close = panel["close"]
    n_stocks = close.shape[1]
    n_days = close.shape[0]
    log.info("  OHLCV 就绪: %d 只 × %d 日", n_stocks, n_days)

    # ── 2. 叠加竞价数据 ──
    log.info("\n[2/4] 叠加竞价数据 ...")
    try:
        panel2 = load_auction_panel(UNIVERSE, PERIOD)
        if panel2:
            for k in ["fund:auction_vol", "fund:auction_vol_ratio"]:
                if k in panel2:
                    panel[k] = panel2[k]
            log.info("  竞价数据叠加完成")
    except Exception as exc:
        log.warning("竞价加载失败: %s", exc)

    # ── 3. 叠加问财数据 ──
    log.info("\n[3/4] 叠加问财数据 ...")
    cache_dir = str(Path.home() / ".vibe-trading" / "cache" / "iwencai")
    try:
        p3 = load_iwencai_panel(
            UNIVERSE, PERIOD,
            stock_ids=list(close.columns),
            cache_dir=cache_dir,
        )
        if p3:
            for k in p3:
                if k.startswith("fund:"):
                    panel[k] = p3[k]
            log.info("  问财数据叠加完成")
    except Exception as exc:
        log.warning("问财加载失败: %s", exc)

    log.info("  Panel 最终: %d 只 × %d 日", n_stocks, n_days)

    # ── 4. 计算因子 ──
    log.info("\n[4/4] 计算因子 ...")
    forward_ret = close.pct_change(periods=1).shift(-1)

    registry = Registry()
    results = []

    all_ids = ALPHA_IDS_ORIG + ALPHA_IDS_V2
    for alpha_id in all_ids:
        try:
            meta = registry.get(alpha_id)
        except KeyError:
            log.warning("  alpha %s 未找到", alpha_id)
            continue

        nickname = meta.meta.get("nickname", "")
        version = "v2" if alpha_id.endswith("_v2") or alpha_id == "my_residual_flow" else "原版"
        log.info("  [%s] %s ...", version, alpha_id)
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

        results.append({
            "alpha_id": alpha_id,
            "nickname": nickname,
            "version": version,
            "n_days": n,
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(ic_std, 4),
            "ir": round(ir, 4),
            "ic_pos_ratio": round(ic_pos_ratio, 4),
            "t_stat": round(t_stat, 2),
            "compute_seconds": round(compute_t, 2),
            "nan_ratio_pct": round(nan_pct, 1),
        })

        status = "✅" if abs(t_stat) > 2 and ic_pos_ratio >= 0.55 else " "
        log.info("    %s IC=%.4f  IR=%.4f  IC+ratio=%.2f  t=%.2f  n=%d",
                 status, ic_mean, ir, ic_pos_ratio, t_stat, n)

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("结果汇总")
    log.info("=" * 100)
    log.info(f"{'Alpha':32s} {'Ver':4s} {'IC_mean':>8s} {'IR':>8s} {'IC+%':>6s} {'t':>6s} {'n':>5s} {'NaN%':>6s} {'Status'}")
    log.info("-" * 100)
    results.sort(key=lambda r: r["ir"], reverse=True)
    for r in results:
        status = "✅" if abs(r["t_stat"]) > 2 and r["ic_pos_ratio"] >= 0.55 else " "
        log.info(f"{r['alpha_id']:32s} {r['version']:4s} {r['ic_mean']:8.4f} {r['ir']:8.4f} "
                 f"{r['ic_pos_ratio']:6.2f} {r['t_stat']:6.2f} {r['n_days']:5d} "
                 f"{r['nan_ratio_pct']:6.1f} {status}")

    elapsed = time.time() - t0
    log.info("-" * 100)
    log.info("总耗时: %.0f 秒", elapsed)

    out_dir = Path("output") / "alt_bench_v2"
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

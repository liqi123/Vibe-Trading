"""14因子 vs 16因子v2 回测对比

回测条件：
- 区间：2025-01-02 ~ 2026-07-10
- 股池：全A股（按因子排名选Top 5%）
- 调仓：每日
- 手续费：0.15%（买卖各0.1%+印花税0.1%）
- 滑点：0.1%
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backtest")

UNIVERSE = "all-a-share"
PERIOD = "2025-01-02/2026-07-10"
TOP_PCT = 0.05  # 选Top 5%
COMMISSION = 0.0015  # 0.15% 手续费
SLIPPAGE = 0.001  # 0.1% 滑点


def run_backtest(
    factor_df: pd.DataFrame,
    close: pd.DataFrame,
    top_pct: float = TOP_PCT,
    commission: float = COMMISSION,
    slippage: float = SLIPPAGE,
) -> dict:
    """运行简单回测：每日选Top N等权持有"""
    # 计算每日收益率
    returns = close.pct_change()

    # 生成持仓信号：每日选因子排名前top_pct的股票
    positions = pd.DataFrame(0.0, index=factor_df.index, columns=factor_df.columns)
    for date in factor_df.index:
        row = factor_df.loc[date].dropna()
        if len(row) < 10:
            continue
        n_select = max(1, int(len(row) * top_pct))
        top_stocks = row.nlargest(n_select).index
        positions.loc[date, top_stocks] = 1.0 / n_select  # 等权

    # 计算组合收益（考虑换仓成本）
    portfolio_returns = (positions.shift(1) * returns).sum(axis=1)

    # 计算换手率并扣除成本
    turnover = positions.diff().abs().sum(axis=1) / 2  # 单边换手
    cost = turnover * (commission + slippage)
    portfolio_returns -= cost

    # 累计收益
    cumulative = (1 + portfolio_returns).cumprod()

    # 计算指标
    total_return = cumulative.iloc[-1] - 1
    n_days = len(portfolio_returns.dropna())
    annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
    annual_vol = portfolio_returns.std() * np.sqrt(252)
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0
    max_drawdown = (cumulative / cumulative.cummax() - 1).min()
    win_rate = (portfolio_returns > 0).mean()
    avg_turnover = turnover.mean()

    # 按年分解
    yearly = {}
    for yr in [2025, 2026]:
        yr_ret = portfolio_returns[portfolio_returns.index.year == yr]
        if len(yr_ret) > 10:
            yr_cum = (1 + yr_ret).cumprod()
            yr_total = yr_cum.iloc[-1] - 1
            yr_vol = yr_ret.std() * np.sqrt(252)
            yearly[yr] = {
                "return": round(yr_total * 100, 2),
                "sharpe": round(yr_total / yr_vol if yr_vol > 0 else 0, 2),
                "days": len(yr_ret),
            }

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "annual_vol": round(annual_vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "win_rate": round(win_rate * 100, 1),
        "avg_turnover": round(avg_turnover * 100, 1),
        "n_days": n_days,
        "yearly": yearly,
    }


def main():
    from strategies.composite.composite_14factor import compute_14factor
    from strategies.composite.composite_16factor_v2 import compute_16factor_v2

    t0 = time.time()
    log.info("=" * 80)
    log.info("14因子 vs 16因子v2 回测对比")
    log.info("Period: %s  Top: %.0f%%  Commission: %.2f%%  Slippage: %.2f%%",
             PERIOD, TOP_PCT * 100, COMMISSION * 100, SLIPPAGE * 100)
    log.info("=" * 80)

    # ── 1. 加载 panel ──
    log.info("\n[1/3] 加载数据 ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("Panel empty, abort.")
        return

    close = panel["close"]
    n_stocks = close.shape[1]
    n_days = close.shape[0]
    log.info("  OHLCV: %d 只 × %d 日", n_stocks, n_days)

    # ── 2. 叠加问财数据 ──
    log.info("\n[2/3] 叠加问财数据 ...")
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

    # ── 3. 计算因子并回测 ──
    log.info("\n[3/3] 计算因子并回测 ...")

    results = {}
    for name, compute_fn in [("14-Factor", compute_14factor), ("16-Factor v2", compute_16factor_v2)]:
        log.info("  计算 %s ...", name)
        tf = time.time()
        try:
            factor_df = compute_fn(panel)
        except Exception as exc:
            log.warning("  compute failed: %s", exc)
            continue
        compute_t = time.time() - tf
        log.info("    compute: %.2fs", compute_t)

        log.info("  回测 %s ...", name)
        bt = run_backtest(factor_df, close)
        results[name] = bt

    # ── 报告 ──
    log.info("\n" + "=" * 100)
    log.info("回测结果")
    log.info("=" * 100)
    log.info(f"{'Strategy':16s} {'总收益':>8s} {'年化':>8s} {'夏普':>6s} {'最大回撤':>8s} {'胜率':>6s} {'换手':>6s}")
    log.info("-" * 100)
    for name, bt in results.items():
        log.info(f"{name:16s} {bt['total_return']:7.1f}% {bt['annual_return']:7.1f}% "
                 f"{bt['sharpe']:6.2f} {bt['max_drawdown']:7.1f}% "
                 f"{bt['win_rate']:5.1f}% {bt['avg_turnover']:5.1f}%")
        if bt.get("yearly"):
            parts = []
            for yr in sorted(bt["yearly"]):
                yd = bt["yearly"][yr]
                parts.append(f"{yr}:{yd['return']:+.1f}%")
            log.info(f"{'':16s}   年度: {', '.join(parts)}")

    # 对比提升
    if len(results) == 2:
        names = list(results.keys())
        r14, r16 = results[names[0]], results[names[1]]
        log.info("-" * 100)
        log.info("%s vs %s:", names[1], names[0])
        log.info("  总收益: %+.1f%%  年化: %+.1f%%  夏普: %+.2f",
                 r16["total_return"] - r14["total_return"],
                 r16["annual_return"] - r14["annual_return"],
                 r16["sharpe"] - r14["sharpe"])

    elapsed = time.time() - t0
    log.info("\n总耗时: %.0f 秒", elapsed)

    # 保存结果
    out_dir = Path("output") / "backtest_14v16"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps({
        "config": {
            "period": PERIOD,
            "top_pct": TOP_PCT,
            "commission": COMMISSION,
            "slippage": SLIPPAGE,
        },
        "results": results,
    }, ensure_ascii=False, indent=2))
    log.info("JSON saved: %s", out_path)


if __name__ == "__main__":
    main()

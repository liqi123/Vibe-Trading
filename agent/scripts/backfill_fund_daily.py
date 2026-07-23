"""
问财数据回补脚本 — 回填 fund_daily 表

用法:
    cd Vibe-Trading/agent
    python scripts/backfill_fund_daily.py

只补 fund_daily 表中缺失的日期，已存在的数据跳过。
每次 API 调用间隔 1.5s（防封），报错即停。
"""
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

PERIOD = "2024-01-02/2026-07-23"
UNIVERSE = "all-a-share"


def main():
    log.info("=" * 60)
    log.info("问财数据回补: %s  %s", UNIVERSE, PERIOD)
    log.info("=" * 60)

    from scripts.alt_data_loader import load_iwencai_panel

    # 加载 OHLCV panel → 获取日期索引和股票列表
    log.info("加载 OHLCV panel ...")
    from src.tools.alpha_bench_tool import _load_universe_panel
    panel = _load_universe_panel(UNIVERSE, PERIOD)
    if not panel:
        log.error("OHLCV panel 加载失败，终止")
        sys.exit(1)

    close = panel.get("close")
    if close is None:
        log.error("panel 中无 close 数据，终止")
        sys.exit(1)

    log.info("OHLCV 就绪: %d 只股票 × %d 个交易日", close.shape[1], close.shape[0])

    # 检查 fund_daily 现有数据范围
    from scripts.alt_data_loader import _init_fund_table, _load_from_db
    db_conn = _init_fund_table()
    if db_conn:
        all_date_strs = [d.strftime("%Y-%m-%d") for d in close.index]
        all_stock_ids = list(close.columns)
        existing = _load_from_db(db_conn, all_date_strs, all_stock_ids)
        existing_dates = set()
        for fv in existing.values():
            existing_dates.update(fv.keys())
        log.info("fund_daily 已有 %d 天数据，需补充 %d 天",
                 len(existing_dates), len(all_date_strs) - len(existing_dates))
        db_conn.close()

    if len(existing_dates) == len(all_date_strs):
        log.info("所有数据已存在，无需回补")
        return

    cache_dir = str(Path.home() / ".vibe-trading" / "cache" / "iwencai")
    log.info("JSON 缓存目录: %s", cache_dir)
    log.info("开始逐日回补（每次 API 间隔 1.5s）...")

    result = load_iwencai_panel(
        UNIVERSE, PERIOD,
        stock_ids=list(close.columns),
        cache_dir=cache_dir,
    )

    if not result:
        log.error("回补失败: load_iwencai_panel 返回空")
        sys.exit(1)

    log.info("=" * 60)
    log.info("回补完成")
    for k in sorted(result):
        if k.startswith("fund:"):
            df = result[k]
            n = int(df.notna().any().sum()) if hasattr(df, 'notna') else 0
            log.info("  %s: %d 只股票有数据", k, n)
    log.info("=" * 60)


if __name__ == "__main__":
    main()

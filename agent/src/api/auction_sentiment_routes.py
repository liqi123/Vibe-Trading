"""竞价情绪四阶段判断 API。

计算在根项目 data/auction_sentiment_check.py（本地 auction 表 + daily_kline + 腾讯实时），
LLM 叙事在 data/auction_sentiment_ai.py。端点（前端经 api.tools 代理访问）：
  GET  /tools/auction-sentiment/check?date=2026-08-25&stage=4   四阶段结构化结果
  POST /tools/auction-sentiment/narrative?date=2026-08-25       AI 解读（慢，~1分钟）
"""

from __future__ import annotations

import sys
import traceback
from datetime import date as _date
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/auction-sentiment", tags=["auction-sentiment"])


@router.get("/check")
def auction_sentiment_check(date: str = "", stage: int = 0):
    """四阶段竞价情绪检查。date 缺省取今天；stage 缺省按时段自动（盘后=全量复盘）。"""
    from data.auction_sentiment_check import get_today_str, run

    date_str = date or get_today_str()
    try:
        payload = run(date_str=date_str, stage=stage or None, verbose=False)
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "error": f"{exc}",
            "trace": traceback.format_exc(limit=3),
            "date": date_str,
        }
    return {"ok": True, **payload}


@router.post("/narrative")
def auction_sentiment_narrative(payload: dict | None = None, date: str = "", refresh: bool = False):
    """AI 叙事解读。同日缓存命中直接返回；refresh=true 强制重新生成。

    date/refresh 可经 query 或 body 传入（与 /tools/sentiment/ai-analysis 一致）。
    """
    if payload:
        date = date or payload.get("date", "")
        refresh = refresh or bool(payload.get("refresh", False))
    from data.auction_sentiment_ai import generate_narrative, load_narrative_cache
    from data.auction_sentiment_check import get_today_str, run

    date_str = date or get_today_str()
    if not refresh:
        cached = load_narrative_cache(date_str)
        if cached:
            return {"ok": True, "date": date_str, "narrative": cached, "cached": True}
    try:
        result = run(date_str=date_str, stage=None, verbose=False)
        text = generate_narrative(result, force=bool(refresh))
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"{exc}", "date": date_str, "narrative": ""}
    return {"ok": True, "date": date_str, "narrative": text, "cached": False}


def register_auction_sentiment_routes(app):
    """Register auction sentiment (竞价情绪) routes on the FastAPI app."""
    app.include_router(router)

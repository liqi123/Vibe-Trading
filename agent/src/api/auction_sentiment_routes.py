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

_STAGE_TIME = {
    2: "09:25 竞价结束",
    3: "09:35 验证资金",
    4: "09:45 主线合力",
    5: "10:00 选定个股",
}


def _read_stage_narrative(date_str: str, stage: int) -> str:
    """读取单阶段项目 LLM 分析缓存（data/auction_sentiment/narrative/{date}_stage{N}.md）。"""
    try:
        from data.auction_sentiment_ai import load_stage_narrative_cache

        return load_stage_narrative_cache(date_str, stage) or ""
    except Exception:
        return ""


def _read_stage_result(date_str: str, stage: int) -> dict | None:
    """读取单阶段规则结果快照（同目录 {date}_stage{N}.json），生成分析时一并落盘。"""
    try:
        from data.auction_sentiment_ai import load_stage_result_cache

        return load_stage_result_cache(date_str, stage)
    except Exception:
        return None


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
    # 挂阶段报告：阶段 2/3/4/5 走项目 LLM（本地+腾讯数据），
    # 阶段 1（盘前）需联网检索外围，仍走豆包/DeepSeek 网页版综合。
    # 当天生成过分析的阶段：用生成那一刻的快照回填（信号表 + 结论），重进页面不变；
    # 当前时段还没到的阶段（stages 里没有）也照样补卡，避免早盘进去一片空白。
    stages = payload.get("stages") or []
    by_stage = {int(s.get("stage") or 0): s for s in stages}
    for st in (2, 3, 4, 5):
        snap = _read_stage_result(date_str, st)
        report = _read_stage_narrative(date_str, st)
        if not (snap or report):
            continue
        card = by_stage.get(st)
        if snap is None and card is not None and not card.get("skip") and card.get("signals"):
            # 改造前只落了 md：拿这一次的规则结果补一份快照，之后即固化不再重算
            try:
                from data.auction_sentiment_ai import save_stage_result_cache

                save_stage_result_cache(
                    date_str, st, {k: v for k, v in card.items() if k not in ("ai_report", "ai_source")}
                )
                snap = card
            except Exception:
                snap = None
        if card is None:
            card = {"stage": st, "time": (snap or {}).get("time") or _STAGE_TIME.get(st, "")}
            stages.append(card)
        if snap:
            for key in ("time", "signals", "bad_count", "decision"):
                if key in snap:
                    card[key] = snap[key]
            card["cached"] = True
        card["ai_report"] = report
        card["ai_source"] = "project-llm" if report else ""
    payload["stages"] = stages
    if payload.get("overall") is None:
        from data.auction_sentiment_check import summarize_stages

        payload["overall"] = summarize_stages(stages)
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


@router.post("/stage-narrative")
def auction_stage_narrative(
    payload: dict | None = None, date: str = "", stage: int = 0, refresh: bool = False
):
    """单阶段（2/3/4/5）项目 LLM 分析：本地竞价数据 + 腾讯实时行情，不经网页版 LLM。

    阶段 1（盘前）不支持——需联网检索外围与新闻，仍走豆包/DeepSeek。
    refresh=true 强制重算；同日缓存命中直接返回。
    """
    if payload:
        date = date or payload.get("date", "")
        stage = stage or int(payload.get("stage") or 0)
        refresh = refresh or bool(payload.get("refresh", False))
    if stage not in (2, 3, 4, 5):
        return {
            "ok": False,
            "error": "stage 必须为 2/3/4/5（09:25 / 09:35 / 09:45 / 10:00）；盘前阶段 1 走网页版 LLM",
            "date": date,
            "stage": stage,
            "narrative": "",
        }
    from data.auction_sentiment_ai import generate_stage_narrative, load_stage_narrative_cache
    from data.auction_sentiment_check import get_today_str

    date_str = date or get_today_str()
    if not refresh:
        cached = load_stage_narrative_cache(date_str, stage)
        if cached:
            return {
                "ok": True,
                "date": date_str,
                "stage": stage,
                "narrative": cached,
                "cached": True,
            }
    try:
        text = generate_stage_narrative(date_str, stage, force=bool(refresh))
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"{exc}", "date": date_str, "stage": stage, "narrative": ""}
    return {"ok": True, "date": date_str, "stage": stage, "narrative": text, "cached": False}


def register_auction_sentiment_routes(app):
    """Register auction sentiment (竞价情绪) routes on the FastAPI app."""
    app.include_router(router)

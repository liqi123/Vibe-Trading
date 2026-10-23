"""短线复盘 / 盘面数据 API —— 移植自 simonlin1212/vibe-astock（Apache-2.0）。

数据层在根项目的 analysis/vibe/（akshare/东财/腾讯，全免费直连），
多 agent 叙事引擎跑 `python -m analysis.vibe {date}`（OpenRouter / MiMo / 本机 CLI 任一路）。

端点（前端经 api.tools 代理访问）：
  POST /tools/vibe/review/run         后台跑一场复盘（约 5-10 分钟）
  GET  /tools/vibe/review/status/{id} 读取后台任务输出
  GET  /tools/vibe/review             读某日复盘（默认最新），含派生指标/盘面研判/验证条件
  GET  /tools/vibe/review/dates       已有复盘列表（新→旧）
  GET  /tools/vibe/market-data        盘面数据（指数/板块资金/成交额榜/外围/实时打板）
  GET  /tools/vibe/firstboard         当日首板池与封板结构
  GET  /tools/vibe/weekly             近 5 交易日热度 + 龙头谱系
  GET  /tools/vibe/stats/theme-rotation   近 N 日题材轮动（问财题材串）
  GET  /tools/vibe/stats/zt-samples       涨停样本（次日表现按封板/板位/情绪分组）
  GET  /tools/vibe/stats/emotion-history  每日情绪读数序列 + 今日分位
  GET  /tools/vibe/stats/structure-change 近 10 日 vs 前 20 日读数移位
  POST /tools/vibe/stats/capture           回补最近 N 日情绪原料缓存
  POST /tools/vibe/stats/weekly-ai/run     后台生成 AI 周报（LLM）
  GET  /tools/vibe/stats/weekly-ai/status/{id} 读取周报任务输出
  GET  /tools/vibe/stats/weekly-ai         读最新已缓存的 AI 周报
  GET  /tools/vibe/stats/emotion-path      六时点情绪路径（当日）
  POST /tools/vibe/stats/emotion-path/capture  采集当前时点快照
  GET  /tools/vibe/stats/today-emotion     今日情绪完整页（天梯/断层/封板质量/溢价/周期）
  GET  /tools/vibe/stats/movers            盯盘异动（3 分钟 ±1.5% / 封板开板，codes 缺省=自选池）
  GET  /tools/vibe/stats/ladder-live       昨日涨停梯队 + 今日晋级/炸板状态（盯盘页）
  GET  /tools/vibe/stats/stock-overview    个股深挖·概览（行情/财务摘要/估值分位/基本面）
  GET  /tools/vibe/stats/pool              自选池（三类分组+报价+已了结历史+XIRR）
  GET  /tools/vibe/stats/news              个股新闻（问财，codes 缺省=自选池）
  GET  /tools/vibe/stats/research          个股研报列表（东财 reportapi）
  GET  /tools/vibe/stats/calendar          事件日历（财报预约+限售解禁，TTL 6h）
  GET  /tools/vibe/stats/candidates        候选池（PE/PB/市值/换手/成交额筛选，三档范围）
  POST /tools/vibe/stats/task/{kind}       LLM 后台任务 debate/digest/sector
  GET  /tools/vibe/stats/task/{kind}/latest  读最新缓存（?code=）
  GET  /tools/vibe/stats/task/{kind}/{id}  任务实时输出
  GET  /tools/vibe/stats/backtests         回测 run 列表（agent/runs/bt_*）
  POST /tools/vibe/stats/backtests/gen     LLM 根据 idea 生成 run（config+signal_engine）
  POST /tools/vibe/stats/backtests/run     运行一个 run 目录
  GET  /tools/vibe/stats/backtests/status/{id}  gen/run 任务实时输出
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_TREE_ROOT = Path(__file__).resolve().parents[4]   # trading 根（引擎所在）
_PAPER_DIR = _TREE_ROOT / "paper"
_WK_DIR = os.path.expanduser("~/.duanxian-agents/weekly")

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/vibe", tags=["vibe"])


def _engine_env() -> dict:
    """子进程环境：能 import analysis.vibe + 有 LLM 凭据。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_TREE_ROOT) + (os.pathsep + existing if existing else "")
    return env


class RunReviewRequest(BaseModel):
    date: str = ""


@router.post("/review/run")
def run_review(req: RunReviewRequest):
    """后台跑一场复盘，返回 task_id（输出写 paper/script_output_vibe_{id}.txt）。"""
    date = req.date or ""
    task_id = uuid.uuid4().hex[:8]
    output_file = _PAPER_DIR / f"script_output_vibe_{task_id}.txt"
    args = ["python", "-X", "utf8", "-m", "analysis.vibe"]
    if date:
        args.append(date)
    output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 执行中...\n", encoding="utf-8")

    def _run():
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(_TREE_ROOT), env=_engine_env(), bufsize=1,
            )
            lines = []
            for line in iter(proc.stdout.readline, b""):
                text = line.decode("utf-8", errors="replace")
                lines.append(text)
                content = f"[{datetime.now().strftime('%H:%M:%S')}] 执行中...\n" + "".join(lines)
                output_file.write_text(content, encoding="utf-8")
            proc.stdout.close()
            proc.wait(timeout=10)
            ts = datetime.now().strftime("%H:%M:%S")
            output_file.write_text("".join(lines) + f"\n[{ts}] 执行完成 (exit={proc.returncode})\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            try:
                existing = output_file.read_text(encoding="utf-8")
            except Exception:
                existing = ""
            output_file.write_text(existing + f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {str(exc)[:200]}\n", encoding="utf-8")

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/review/status/{task_id}")
def review_status(task_id: str):
    """读取后台复盘任务的实时输出。"""
    output_file = _PAPER_DIR / f"script_output_vibe_{task_id}.txt"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    return {"content": output_file.read_text(encoding="utf-8")}


@router.get("/review")
def get_review(date: str = ""):
    """读某日复盘（默认最新）；未跑过返回 payload=None。"""
    try:
        from analysis.vibe import review_store
        payload = review_store.load(date or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"引擎不可用: {type(exc).__name__}: {str(exc)[:120]}")
    if payload is None:
        return {"requested_date": date, "payload": None}
    return {"requested_date": date, "payload": payload}


@router.get("/review/dates")
def review_dates():
    try:
        from analysis.vibe import review_store
        return {"dates": review_store.dates()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"引擎不可用: {type(exc).__name__}: {str(exc)[:120]}")


@router.get("/market-data")
def market_data():
    """盘面数据：大盘情绪 / 板块资金 / 成交额榜 / 全球指数 / 隔夜外围 / 实时打板。"""
    from analysis.vibe.vr import gstock, market
    from analysis.vibe import live_emotion, overseas

    def safe(name, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001  单块失败不拖垮整页
            return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    return {
        "overview": safe("overview", market.get_overview),
        "emotion": safe("emotion", market.get_short_term_emotion),
        "turnover_top": safe("turnover_top", market.get_turnover_top),
        "global_indices": safe("global_indices", gstock.global_indices),
        "overseas": safe("overseas", overseas.overseas_snapshot),
        "live_emotion": safe("live_emotion", live_emotion.snapshot),
    }


@router.get("/firstboard")
def firstboard(date: str = ""):
    """当日首板池与封板结构（东财涨停池，免费无 key）。"""
    from analysis.vibe.vr import firstboard as fb
    try:
        return fb.get_first_board()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _weekly_fresh(cached: dict) -> bool:
    """缓存是否仍是最新已收盘交易日窗口。判不了→按新鲜处理不硬刷。"""
    from analysis.vibe.weekly import LINEAGE_SCHEMA
    days = cached.get("days") or []
    if not days:
        return False
    if cached.get("lineage_schema") != LINEAGE_SCHEMA:
        return False
    try:
        from analysis.vibe.weekly import _last_trade_dates
        latest = _last_trade_dates(1)
        expected = latest[-1] if latest else None
    except Exception:  # noqa: BLE001
        expected = None
    return expected is None or days[-1].get("date") == expected


@router.get("/weekly")
def weekly():
    """近 5 交易日热度 + 龙头谱系（缓存按交易日过期，重算约 40s）。"""
    path = os.path.join(_WK_DIR, "latest.json")
    cached = None
    try:
        with open(path, encoding="utf-8") as fh:
            cached = json.load(fh)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        cached = None
    if cached and _weekly_fresh(cached):
        return cached
    from analysis.vibe import weekly as wk
    w = wk.build_weekly(n=5)
    if not w.get("error") and any(d.get("limit_up") is not None for d in (w.get("days") or [])):
        os.makedirs(_WK_DIR, exist_ok=True)
        tmp = path + f".{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(w, fh, ensure_ascii=False)
        os.replace(tmp, path)
    return w


@router.get("/stats/theme-rotation")
def stats_theme_rotation(days: int = 5, top: int = 20):
    """近 N 日题材轮动（问财题材串口径，需 IWENCAI_API_KEY 或已有缓存）。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.theme_rotation(days=days, top=top)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/zt-samples")
def stats_zt_samples(days: int = 20, end: str = ""):
    """涨停样本：昨日涨停股次日表现，按封板时间/板位/入场日情绪分组。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.zt_samples(days=days, end=end or None)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/emotion-history")
def stats_emotion_history(days: int = 30):
    """每日情绪读数序列 + 今日分位 + 近 10 日趋势。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.emotion_history(days=days)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/structure-change")
def stats_structure_change(date: str = "", recent: int = 10, base: int = 20):
    """近 N 日 vs 前 M 日：各读数日中位数移位对比。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.structure_change(date=date or None, recent=recent, base=base)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.post("/stats/capture")
def stats_capture(days: int = 25):
    """回补最近 N 个已收盘交易日的情绪原料缓存（东财约一个月保留期内）。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.capture_recent(days=days)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/emotion-path")
def stats_emotion_path(date: str = ""):
    """六时点情绪路径（当日或指定日）。"""
    from analysis.vibe import emotion_path
    try:
        return emotion_path.path(date or None)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.post("/stats/emotion-path/capture")
def stats_emotion_path_capture(date: str = ""):
    """采集当前时点快照（幂等；非交易时段/已采过会说明原因）。"""
    from analysis.vibe import emotion_path
    try:
        return emotion_path.capture(date or None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/today-emotion")
def stats_today_emotion(date: str = ""):
    """今日情绪完整页：连板天梯 / 梯队断层 / 封板质量 / 连板溢价 / 赚钱效应 / 情绪周期。"""
    from analysis.vibe import short_stats
    try:
        return short_stats.today_emotion(date or None)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/movers")
def stats_movers(codes: str = "", threshold: float = 1.5, minutes: int = 3, lookback: int = 30):
    """盯盘异动：盘中 3 分钟 ±1.5% 急拉急跌 / 封板开板（codes 缺省取自选池）。"""
    from analysis.vibe import movers
    code_list = [c.strip() for c in codes.split(",") if c.strip()] or None
    try:
        return movers.scan(code_list, threshold=threshold, minutes=minutes, lookback=lookback)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/ladder-live")
def stats_ladder_live():
    """昨日涨停梯队 + 今日逐票晋级/炸板/未板状态（盯盘页）。"""
    from analysis.vibe import live_emotion
    try:
        return live_emotion.ladder_live()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/stock-overview")
def stats_stock_overview(code: str):
    """个股深挖·概览：行情 / 财务摘要 / 估值分位 / 基本面（块级降级）。"""
    from analysis.vibe import stock_overview
    try:
        return stock_overview.overview(code)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/auction-strength")
def stats_auction_strength(date: str = ""):
    """竞价强弱：昨日涨停池 09:25 竞价（中位/均值/高开占比/低开>5%/分板位/最高标）。"""
    from analysis.vibe import auction_strength
    try:
        return auction_strength.compute(date or None)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.post("/stats/weekly-ai/run")
def stats_weekly_ai_run(req: RunReviewRequest):
    """后台生成 AI 周报（LLM，约 1-3 分钟），返回 task_id。"""
    n = 5
    date = req.date or ""
    task_id = uuid.uuid4().hex[:8]
    output_file = _PAPER_DIR / f"script_output_vibe_wkai_{task_id}.txt"

    def _run():
        try:
            from analysis.vibe import short_stats
            output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 资料包准备中...\n", encoding="utf-8")
            result = short_stats.build_weekly_ai(n=n, force=True)
            ts = datetime.now().strftime("%H:%M:%S")
            if result.get("available"):
                output_file.write_text(f"[{ts}] 执行完成 (exit=0)\n", encoding="utf-8")
            else:
                reason = result.get("reason", "未知错误")
                output_file.write_text(f"[{ts}] 失败: {reason}\n[{ts}] 执行完成 (exit=1)\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            ts = datetime.now().strftime("%H:%M:%S")
            output_file.write_text(f"[{ts}] 错误: {str(exc)[:200]}\n[{ts}] 执行完成 (exit=1)\n", encoding="utf-8")

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/stats/weekly-ai/status/{task_id}")
def stats_weekly_ai_status(task_id: str):
    """读取 AI 周报后台任务的实时输出。"""
    output_file = _PAPER_DIR / f"script_output_vibe_wkai_{task_id}.txt"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    return {"content": output_file.read_text(encoding="utf-8")}


@router.get("/stats/weekly-ai")
def stats_weekly_ai(n: int = 5):
    """读最新已缓存的 AI 周报（week_end = 最近 n 交易日的最后一天）。"""
    from analysis.vibe import trade_calendar
    dates = trade_calendar.last_trade_dates(n)
    if not dates:
        return {"available": False, "reason": "交易日历不可用"}
    last = dates[-1]
    path = os.path.join(_WK_DIR, f"ai_{last}.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            pass
    return {"available": False, "week_end": last, "dates": dates, "reason": "尚未生成"}


# ------------------------------------------------ 自选池工作台（候选池/资讯/资料库/事件日历）

@router.get("/stats/pool")
def stats_pool():
    """自选池：positions 三类分组 + 实时报价 + 已了结历史 + 每笔年化(XIRR)。"""
    from analysis.vibe import watchlist_tools
    try:
        return watchlist_tools.pool_summary()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/news")
def stats_news(codes: str = "", size: int = 5):
    """个股新闻（问财）。codes 逗号分隔，缺省=自选池 holding+observation。"""
    from analysis.vibe import watchlist_tools
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    try:
        return watchlist_tools.news_for(code_list, size=size)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/research")
def stats_research(code: str = "", limit: int = 20):
    """个股研报列表（东财 reportapi，免 key，含 pdf 直链）。"""
    from analysis.vibe import watchlist_tools
    try:
        return watchlist_tools.research_for(code, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/calendar")
def stats_calendar(codes: str = "", days: int = 120):
    """事件日历：财报预约披露 + 限售解禁（自选池，仅未来事件，TTL 6h）。"""
    from analysis.vibe import watchlist_tools
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    try:
        return watchlist_tools.calendar_for(code_list, days=days)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/candidates")
def stats_candidates(
    scope: str = "watchlist",
    q: str = "",
    limit: int = 300,
    pe_min: Optional[float] = None,
    pe_max: Optional[float] = None,
    pb_min: Optional[float] = None,
    pb_max: Optional[float] = None,
    mcap_min: Optional[float] = None,
    mcap_max: Optional[float] = None,
    turnover_min: Optional[float] = None,
    turnover_max: Optional[float] = None,
    amount_min: Optional[float] = None,
):
    """候选池：腾讯实时行情按 PE/PB/市值/换手/成交额筛选，scope=watchlist/holding/market。"""
    from analysis.vibe import candidates
    try:
        return candidates.screen(
            scope,
            pe_min=pe_min, pe_max=pe_max, pb_min=pb_min, pb_max=pb_max,
            mcap_min=mcap_min, mcap_max=mcap_max,
            turnover_min=turnover_min, turnover_max=turnover_max,
            amount_min=amount_min, q=q, limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


# ---------------------------------------------------------------- LLM 任务（辩论/深挖/板块）

_TASK_KINDS = ("debate", "digest", "sector")


class TaskRequest(BaseModel):
    code: str = ""
    name: str = ""


@router.post("/stats/task/{kind}")
def stats_task_run(kind: str, req: TaskRequest):
    """后台 LLM 任务：debate=多空辩论 / digest=个股深挖 / sector=板块研究。"""
    if kind not in _TASK_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown task kind: {kind}")
    task_id = uuid.uuid4().hex[:8]
    output_file = _PAPER_DIR / f"script_output_vibe_task_{kind}_{task_id}.txt"

    def _append(text: str) -> None:
        try:
            old = output_file.read_text(encoding="utf-8")
        except OSError:
            old = ""
        output_file.write_text(old + text, encoding="utf-8")

    def _run():
        from analysis.vibe import llm_tasks
        from analysis.vibe.watchlist_tools import bare

        ts = datetime.now().strftime("%H:%M:%S")
        _append(f"[{ts}] 资料包准备中...\n")

        def prog(msg: str) -> None:
            _append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

        try:
            if kind == "sector":
                result = llm_tasks.run_sector_research(progress=prog)
            else:
                code6 = bare(req.code)
                if not code6:
                    _append(f"[{ts}] 失败: 缺少 code\n[{ts}] 执行完成 (exit=1)\n")
                    return
                fn = llm_tasks.run_debate if kind == "debate" else llm_tasks.run_digest
                result = fn(code6, req.name, progress=prog)
            ts = datetime.now().strftime("%H:%M:%S")
            if result.get("available"):
                md = result.get("markdown", "")
                _append(f"\n{md}\n\n[{ts}] 执行完成 (exit=0)\n")
            else:
                _append(f"[{ts}] 失败: {result.get('reason', '未知错误')}\n[{ts}] 执行完成 (exit=1)\n")
        except Exception as exc:  # noqa: BLE001
            ts = datetime.now().strftime("%H:%M:%S")
            _append(f"[{ts}] 错误: {str(exc)[:200]}\n[{ts}] 执行完成 (exit=1)\n")

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/stats/task/{kind}/latest")
def stats_task_latest(kind: str, code: str = ""):
    """读最新缓存的 LLM 任务产物（debate/digest 需 code；sector 忽略 code）。"""
    if kind not in _TASK_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown task kind: {kind}")
    from analysis.vibe import llm_tasks, watchlist_tools

    key = "" if kind == "sector" else watchlist_tools.bare(code)
    try:
        return llm_tasks.latest(kind, key)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


@router.get("/stats/task/{kind}/{task_id}")
def stats_task_status(kind: str, task_id: str):
    """读取 LLM 后台任务的实时输出。"""
    if kind not in _TASK_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown task kind: {kind}")
    output_file = _PAPER_DIR / f"script_output_vibe_task_{kind}_{task_id}.txt"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    return {"content": output_file.read_text(encoding="utf-8")}


# ------------------------------------------------------------------ 对话回测
# run 目录统一放 agent/runs/ 下（backtest_tool.safe_run_dir 白名单内），
# gen = LLM 根据 idea 生成 config.json + code/signal_engine.py，run = 复用
# src.tools.backtest_tool.run_backtest 校验+执行（emit_progress 在 API 线程静默）。
_AGENT_ROOT = Path(__file__).resolve().parents[2]           # Vibe-Trading/agent
_RUNS_ROOT = _AGENT_ROOT / "runs"
_BT_LOCK = threading.Lock()
_BT_GEN_ACTIVE: set[str] = set()

_BT_PROMPT = """你是 A股量化回测的代码生成器。根据用户的想法，产出一个可直接运行的回测 run：
config.json + code/signal_engine.py。

## 硬性契约（引擎会 AST 严格校验，违反直接拒绝）
1. code 只允许：from __future__ / import pandas / import numpy / import 其它已给模块、
   函数定义、class 定义、字面量赋值。禁止装饰器、可执行顶层语句、网络请求、文件写入、eval/exec。
2. code 必须定义 class SignalEngine：
   - __init__(self, ...) 所有参数带默认值
   - generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]
3. data_map: {symbol: DataFrame}，symbol 形如 "600519.SH"；
   列为 [open, high, low, close, volume]，index 为按日期升序的交易日。
4. generate 返回 {symbol: pd.Series}，Series index=日期，值=目标仓位 ∈[-1,1]
   （引擎按日再平衡；纯多头建议 0~1，可空到 -1）；无信号的 symbol 可省略或全 0。
5. config.json 字段：
   codes（10~30 只 A 股，"600519.SH" 格式）、start_date/end_date（"YYYY-MM-DD"，
   近 12 个月，end_date 不得晚于今天 {today}）、source 固定 "auto"、
   interval "1D"、engine "daily"；可选 initial_capital=1000000、commission_rate=0.0003、
   slippage=0.001、benchmark（如 "000300.SH"）。
6. 核心逻辑控制在 5~40 行，简单可读（动量/反转/均线/量价择时等），面向 A股 T+1。

## 输出格式
只输出一个 JSON 对象（可包在 ```json 围栏内），不要任何其它文字：
{{"config": {{...}}, "code": "完整 python 源码字符串"}}

## 用户想法
{idea}
"""


def _bt_out(task_id: str) -> Path:
    return _PAPER_DIR / f"script_output_vibe_bt_{task_id}.txt"


def _bt_sidecar(task_id: str) -> Path:
    return _PAPER_DIR / f"script_output_vibe_bt_{task_id}.json"


def _bt_extract_json(text: str) -> dict:
    import re

    if not text:
        raise ValueError("LLM 返回为空")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        i, j = text.find("{"), text.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("响应中未找到 JSON 对象")
        raw = text[i : j + 1]
    return json.loads(raw)


class BtGenRequest(BaseModel):
    idea: str = ""


class BtRunRequest(BaseModel):
    run_dir: str = ""


@router.get("/stats/backtests")
def stats_backtests():
    """列出 agent/runs/ 下可运行的回测 run（config + run_card 指标）。"""
    items = []
    if _RUNS_ROOT.is_dir():
        for d in sorted(_RUNS_ROOT.iterdir(), reverse=True):
            cfg_p = d / "config.json"
            if not d.is_dir() or not cfg_p.exists():
                continue
            try:
                cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cfg = {}
            card: dict = {}
            card_p = d / "run_card.json"
            if card_p.exists():
                try:
                    card = json.loads(card_p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    card = {}
            items.append({
                "name": d.name,
                "run_dir": str(d),
                "idea": cfg.get("idea", ""),
                "codes_n": len(cfg.get("codes") or []),
                "start_date": cfg.get("start_date"),
                "end_date": cfg.get("end_date"),
                "source": cfg.get("source"),
                "generated_at": cfg.get("generated_at"),
                "status": "done" if card else "ready",
                "metrics": card.get("metrics") or None,
                "warnings": card.get("warnings") or [],
            })
    return {"available": True, "items": items, "n": len(items)}


@router.post("/stats/backtests/gen")
def stats_backtests_gen(req: BtGenRequest):
    """LLM 根据 idea 生成一个回测 run（config.json + signal_engine.py）。"""
    idea = (req.idea or "").strip()
    if not idea:
        raise HTTPException(status_code=400, detail="idea 不能为空")
    with _BT_LOCK:
        if _BT_GEN_ACTIVE:
            raise HTTPException(status_code=429, detail="已有生成任务在跑，请稍候")
        task_id = uuid.uuid4().hex[:8]
        _BT_GEN_ACTIVE.add(task_id)
    out = _bt_out(task_id)
    out.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 执行中...\n", encoding="utf-8")

    def _run():
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            out.write_text(f"[{ts}] 调用 LLM 生成规则...\n", encoding="utf-8")
            from src.providers.chat import ChatLLM

            prompt = _BT_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"), idea=idea)
            resp = ChatLLM().chat([{"role": "user", "content": prompt}], timeout=300)
            text = resp.content or ""
            payload = _bt_extract_json(text)
            cfg = payload.get("config") or {}
            code = payload.get("code") or ""
            codes = cfg.get("codes") or []
            if not codes or not isinstance(codes, list):
                raise ValueError("config.codes 为空")
            if "class SignalEngine" not in code or "def generate" not in code:
                raise ValueError("code 缺少 class SignalEngine / generate")
            if not (cfg.get("start_date") and cfg.get("end_date")):
                raise ValueError("config 缺少 start_date/end_date")
            cfg.setdefault("source", "auto")
            cfg.setdefault("interval", "1D")
            cfg.setdefault("engine", "daily")
            name = f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
            run_dir = _RUNS_ROOT / name
            (run_dir / "code").mkdir(parents=True, exist_ok=True)
            cfg["idea"] = idea
            cfg["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            (run_dir / "config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (run_dir / "code" / "signal_engine.py").write_text(code, encoding="utf-8")
            result = {"name": name, "run_dir": str(run_dir), "codes_n": len(codes)}
            _bt_sidecar(task_id).write_text(
                json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8"
            )
            ts = datetime.now().strftime("%H:%M:%S")
            out.write_text(
                f"[{ts}] 已生成 {name}（{len(codes)} 只，{cfg.get('start_date')}~{cfg.get('end_date')}）\n"
                f"[{ts}] 执行完成 (exit=0)\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            ts = datetime.now().strftime("%H:%M:%S")
            out.write_text(
                f"[{ts}] 失败: {str(exc)[:300]}\n[{ts}] 执行完成 (exit=1)\n", encoding="utf-8"
            )
        finally:
            with _BT_LOCK:
                _BT_GEN_ACTIVE.discard(task_id)

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.post("/stats/backtests/run")
def stats_backtests_run(req: BtRunRequest):
    """运行 agent/runs/ 下的一个回测 run 目录。"""
    run_path = Path(req.run_dir).resolve()
    if not run_path.is_relative_to(_RUNS_ROOT.resolve()):
        raise HTTPException(status_code=400, detail="run_dir 必须在 agent/runs 下")
    if not (run_path / "config.json").exists():
        raise HTTPException(status_code=400, detail="run_dir 缺少 config.json")
    task_id = uuid.uuid4().hex[:8]
    out = _bt_out(task_id)
    out.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 执行中...\n", encoding="utf-8")

    def _run():
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            from src.tools.backtest_tool import run_backtest

            cfg = json.loads((run_path / "config.json").read_text(encoding="utf-8"))
            out.write_text(
                f"[{ts}] 执行中… source={cfg.get('source')} "
                f"codes={len(cfg.get('codes') or [])} "
                f"{cfg.get('start_date')}~{cfg.get('end_date')}\n",
                encoding="utf-8",
            )
            res = json.loads(run_backtest(str(run_path)))
            tail = (res.get("stdout") or "")[-2500:]
            if res.get("status") != "ok":
                tail += "\n" + (res.get("stderr") or "")[-1500:]
            ts = datetime.now().strftime("%H:%M:%S")
            out.write_text(
                f"[{ts}] 执行中… source={cfg.get('source')} "
                f"codes={len(cfg.get('codes') or [])} "
                f"{cfg.get('start_date')}~{cfg.get('end_date')}\n"
                f"{tail}\n[{ts}] 执行完成 (exit={res.get('exit_code')})\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            ts = datetime.now().strftime("%H:%M:%S")
            out.write_text(
                f"[{ts}] 错误: {str(exc)[:300]}\n[{ts}] 执行完成 (exit=1)\n", encoding="utf-8"
            )

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/stats/backtests/status/{task_id}")
def stats_backtests_status(task_id: str):
    """读取 gen/run 任务的实时输出；gen 成功附带 result（run_dir 等）。"""
    out = _bt_out(task_id)
    if not out.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    resp: dict = {"content": out.read_text(encoding="utf-8")}
    sidecar = _bt_sidecar(task_id)
    if sidecar.exists():
        try:
            resp["result"] = json.loads(sidecar.read_text(encoding="utf-8")).get("result")
        except (OSError, json.JSONDecodeError):
            pass
    return resp


def register_vibe_routes(app):
    """Register vibe (短线复盘/盘面数据) routes on the FastAPI app."""
    app.include_router(router)

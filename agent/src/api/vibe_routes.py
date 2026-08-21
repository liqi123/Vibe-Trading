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


def register_vibe_routes(app):
    """Register vibe (短线复盘/盘面数据) routes on the FastAPI app."""
    app.include_router(router)

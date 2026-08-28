"""淘股吧关注用户交易信号监控 API。

数据/采集在根项目 analysis/external/tgb.py（归档 data/tgb/{date}.jsonl），
端点（前端经 api.tools 代理访问）：
  GET  /tools/tgb/signals?date=2026-08-26   按日读取已归档信号（按用户分组）
  POST /tools/tgb/refresh                   立即轮询一次（--once --force，同步执行）
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/tgb", tags=["tgb"])

_DATA_DIR = _TREE_ROOT / "data" / "tgb"
_POLL_LOCK = threading.Lock()


def _available_dates() -> list[str]:
    if not _DATA_DIR.exists():
        return []
    return sorted((p.stem for p in _DATA_DIR.glob("*.jsonl")), reverse=True)


def _read_follows() -> dict:
    state_path = _DATA_DIR / "state.json"
    if not state_path.exists():
        return {"count": 0, "names": []}
    try:
        st = json.loads(state_path.read_text(encoding="utf-8"))
        names = [v for v in (st.get("follows") or {}).values() if isinstance(v, str)]
        return {"count": len(names), "names": sorted(names)}
    except Exception:
        return {"count": 0, "names": []}


@router.get("/signals")
def tgb_signals(date: str = ""):
    """某日归档信号（按用户分组，动作优先级降序）。缺省取最新有数据的日期。"""
    date = date or (_available_dates()[0] if _available_dates() else datetime.now().strftime("%Y-%m-%d"))
    path = _DATA_DIR / f"{date}.jsonl"
    users: dict[str, list] = {}
    total = conflicts = 0
    seen: set[tuple] = set()
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("kind") != "signal":
                    continue
                key = (rec.get("user"), rec.get("code"), rec.get("action"),
                       rec.get("ts"), rec.get("source"), rec.get("snippet"))
                if key in seen:
                    continue
                seen.add(key)
                users.setdefault(rec.get("user", "?"), []).append({
                    "code": rec.get("code"),
                    "name": rec.get("name"),
                    "action": rec.get("action"),
                    "size": rec.get("size", ""),
                    "snippet": rec.get("snippet"),
                    "source": rec.get("source"),
                    "ts": rec.get("ts"),
                    "conflict": bool(rec.get("conflict")),
                })
        except Exception as exc:  # pragma: no cover
            return {"error": f"读取归档失败: {exc}", "date": date, "dates": _available_dates(), "users": []}
    user_list = [{"user": u, "signals": sigs} for u, sigs in users.items()]
    for g in user_list:
        total += len(g["signals"])
        conflicts += sum(1 for s in g["signals"] if s["conflict"])
    return {
        "date": date,
        "dates": _available_dates()[:30],
        "follows": _read_follows(),
        "users": user_list,
        "total": total,
        "conflicts": conflicts,
    }


@router.post("/refresh")
def tgb_refresh():
    """立即轮询一次淘股吧动态并提取信号（忽略时段限制），返回轮询日志。"""
    if not _POLL_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "已有一次轮询在进行中，请稍后刷新查看"}
    try:
        from analysis.external.tgb import AuthError, TgbClient, run_once

        buf = io.StringIO()
        client = TgbClient(os.environ.get("TGB_USER", ""))
        with contextlib.redirect_stdout(buf):
            run_once(client, force=True)
        return {"ok": True, "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "log": buf.getvalue()}
    except AuthError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}
    finally:
        _POLL_LOCK.release()


def register_tgb_routes(app):
    """Register tgb (淘股吧信号监控) routes on the FastAPI app."""
    app.include_router(router)

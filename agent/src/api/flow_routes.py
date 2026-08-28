"""短线全流程 API（盘前→竞价→盘中→持仓→盘后）。

端点（前端经 api.tools 代理访问）：
  GET  /tools/flow/status?date=2026-08-28   全流程状态（竞价/持仓/复盘/vibe/恐惧贪婪）
  POST /tools/flow/stops                    运行两个模拟盘止盈/止损检查并推企业微信
  POST /tools/flow/target {code,price,portfolio}  为持仓设置止盈目标价
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date as _date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根
_HOME = Path.home()

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/flow", tags=["flow"])

_SENTIMENT_CACHE = _TREE_ROOT / "data" / "market_sentiment" / "sentiment_cache.csv"
_REVIEW_DIR = _TREE_ROOT / "reports" / "output"
_VIBE_DIR = _HOME / ".duanxian-agents" / "reviews"


def _today() -> str:
    return _date.today().isoformat()


def _auction_info(date_str: str) -> dict:
    from utils.config import DB_PATH

    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT COUNT(*), MAX(collect_time) FROM auction WHERE date=?", (date_str,)
        ).fetchone()
        conn.close()
        return {"exists": bool(row and row[0] > 0), "count": row[0] if row else 0, "collect_time": row[1] if row else None}
    except Exception:
        return {"exists": False, "count": 0, "collect_time": None}


def _previous_bizday(date_str: str) -> str:
    from utils.config import DB_PATH, get_date_col

    try:
        date_col, is_int = get_date_col()
        ts = date_str.replace("-", "") if is_int else date_str
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            f"SELECT MAX({date_col}) FROM daily_kline WHERE {date_col} < ?", (ts,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            v = str(row[0])
            return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 else v
    except Exception:
        pass
    # 回退：跳过周末
    d = _date.fromisoformat(date_str) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _fear_greedy() -> dict | None:
    if not _SENTIMENT_CACHE.exists():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(_SENTIMENT_CACHE)
        if df.empty:
            return None
        last = df.iloc[-1]
        return {
            "date": str(last.get("date", "")),
            "afgi": round(float(last.get("afgi", 50)), 1),
            "state": str(last.get("afgi_state", "")),
        }
    except Exception:
        return None


def _file_exists_binary(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


@router.get("/status")
def flow_status(date: str = ""):
    """全流程状态总览：竞价数据、恐惧贪婪、持仓与止盈止损告警、盘前/盘后产物。"""
    date_str = date or _today()
    prev = _previous_bizday(date_str)
    fear = _fear_greedy()
    portfolios = snapshot_portfolios(fast=True)
    return {
        "ok": True,
        "date": date_str,
        "is_today": date_str == _today(),
        "auction": _auction_info(date_str),
        "pre": {
            "fear_greedy": fear,
            "prev_bizday": prev,
            "prev_review": _file_exists_binary(_REVIEW_DIR / f"review_{prev}.md"),
            "prev_vibe": _file_exists_binary(_VIBE_DIR / f"{prev}.json"),
        },
        "holdings": portfolios,
        "post": {
            "review": _file_exists_binary(_REVIEW_DIR / f"review_{date_str}.md"),
            "vibe": _file_exists_binary(_VIBE_DIR / f"{date_str}.json"),
        },
    }


@router.post("/stops")
def flow_stops():
    """运行两个模拟盘止盈/止损快速检查（网页快速版），有告警则推送企业微信。

    快速版不含 V5 深度 ATR 信号；完整检查走 `python -m utils stops`（约 1-2 分钟）。
    """
    portfolios = snapshot_portfolios(fast=True)
    alerts = [{"portfolio": p["name"], **a} for p in portfolios for a in p["alerts"]]
    _notify_stop_alerts(alerts)
    return {"ok": True, "alerts": alerts, "holdings": portfolios, "wecom_pushed": bool(alerts)}


@router.post("/target")
def flow_target(data: dict):
    """为持仓设置止盈目标价。body: {code, price, portfolio('fib'|'v5')}"""
    code = (data or {}).get("code", "")
    price = (data or {}).get("price", 0)
    portfolio = (data or {}).get("portfolio", "v5")
    if not code or price <= 0:
        return {"ok": False, "error": "code 与 price(>0) 必填"}
    if portfolio not in ("fib", "v5"):
        return {"ok": False, "error": f"portfolio 必须为 fib 或 v5，收到 {portfolio}"}
    try:
        done = cli_target(code, float(price), portfolio)
    except Exception as exc:
        return {"ok": False, "error": f"{exc}"}
    if not done:
        return {"ok": False, "error": f"未找到持仓 {code}（{portfolio} 盘）"}
    return {"ok": True, "code": code, "price": float(price), "portfolio": portfolio}


def register_flow_routes(app):
    """Register 短线全流程 routes on the FastAPI app."""
    app.include_router(router)


# 延迟导入（仅在被调用时加载根项目模块，避免启动开销）
def snapshot_portfolios(fast: bool = False):
    from trading.paper_trading import snapshot_portfolios as _sp

    return _sp(fast=fast)


def _notify_stop_alerts(alerts: list):
    from trading.paper_trading import _notify_stop_alerts as _notify

    _notify(alerts)


def cli_target(code: str, price: float, portfolio: str):
    from trading.paper_trading import cli_target as _ct

    _ct(code, price, portfolio)
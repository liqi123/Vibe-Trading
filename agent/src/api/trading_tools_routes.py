"""API routes for custom trading tools.

Provides endpoints for:
- Expectation management (预期管理)
- Paper trading positions (模拟盘)
- Daily scan results (每日选股)
- Market sentiment (市场情绪)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import sys

from fastapi import APIRouter, Depends, HTTPException

# Resolve the project root (trading/) relative to this file's location
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "tdx_data.db"
_PAPER_DIR = _PROJECT_ROOT / "paper"
_UTILS_DIR = _PROJECT_ROOT / "utils"

# Make utils importable for load_state (real-time price updates)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/tools", tags=["trading-tools"])


def _read_json(path: Path) -> dict | list:
    """Read a JSON file, return empty dict on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_db() -> sqlite3.Connection | None:
    """Open the SQLite database if it exists."""
    if _DB_PATH.exists():
        return sqlite3.connect(str(_DB_PATH))
    return None


# ---------------------------------------------------------------------------
# Expectation Management (预期管理)
# ---------------------------------------------------------------------------

@router.get("/expectations")
def get_expectations() -> dict:
    """Return expectation state for all positions."""
    return _read_json(_PAPER_DIR / "expectation_state.json")


@router.get("/expectations/sentiment")
def get_sentiment() -> dict:
    """Return market sentiment state."""
    return _read_json(_PAPER_DIR / "market_sentiment_state.json")


# ---------------------------------------------------------------------------
# Paper Trading (模拟盘)
# ---------------------------------------------------------------------------

@router.get("/portfolio")
def get_portfolio() -> dict:
    """Return V1 paper trading state (Fibonacci strategy) with live prices."""
    try:
        from utils.paper_trading import load_state
        return load_state(_PAPER_DIR / "paper_trading_state.json")
    except Exception:
        return _read_json(_PAPER_DIR / "paper_trading_state.json")


@router.get("/portfolio/v5")
def get_portfolio_v5() -> dict:
    """Return V5 paper trading state (trend strategy) with live prices."""
    try:
        from utils.paper_trading import load_state
        return load_state(_PAPER_DIR / "paper_trading_state_v2.json")
    except Exception:
        return _read_json(_PAPER_DIR / "paper_trading_state_v2.json")


# ---------------------------------------------------------------------------
# Stock Data (个股数据)
# ---------------------------------------------------------------------------

@router.get("/stock/{code}")
def get_stock_info(code: str) -> dict:
    """Return basic stock info from the database."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        # Get latest kline
        cur.execute(
            "SELECT date, open, high, low, close, volume FROM daily_kline "
            "WHERE code = ? ORDER BY date DESC LIMIT 30",
            (code,),
        )
        rows = cur.fetchall()
        # Get stock name
        cur.execute("SELECT name FROM stocks WHERE code = ?", (code,))
        name_row = cur.fetchone()
        return {
            "code": code,
            "name": name_row[0] if name_row else "",
            "kline": [
                {"date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows
            ],
        }
    finally:
        db.close()


@router.get("/stock/{code}/indicators")
def get_stock_indicators(code: str) -> dict:
    """Return computed indicators for a stock."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        cur.execute(
            "SELECT date, open, high, low, close, volume FROM daily_kline "
            "WHERE code = ? ORDER BY date DESC LIMIT 120",
            (code,),
        )
        rows = cur.fetchall()
        if not rows:
            return {"code": code, "indicators": {}}

        # Compute basic indicators
        closes = [r[4] for r in reversed(rows)]
        volumes = [r[5] for r in reversed(rows)]

        def _ma(data: list, n: int) -> float | None:
            if len(data) < n:
                return None
            return sum(data[-n:]) / n

        def _rsi(data: list, n: int = 14) -> float | None:
            if len(data) < n + 1:
                return None
            gains, losses = [], []
            for i in range(-n, 0):
                diff = data[i] - data[i - 1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            avg_gain = sum(gains) / n
            avg_loss = sum(losses) / n
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return round(100 - 100 / (1 + rs), 2)

        return {
            "code": code,
            "indicators": {
                "ma5": _ma(closes, 5),
                "ma10": _ma(closes, 10),
                "ma20": _ma(closes, 20),
                "ma60": _ma(closes, 60),
                "rsi14": _rsi(closes),
                "avg_volume_5": _ma(volumes, 5),
                "avg_volume_20": _ma(volumes, 20),
            },
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Market Overview (市场概览)
# ---------------------------------------------------------------------------

@router.get("/market/overview")
def get_market_overview() -> dict:
    """Return market overview stats."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        # Get latest date
        cur.execute("SELECT MAX(date) FROM daily_kline")
        latest = cur.fetchone()[0]
        if not latest:
            return {"latest_date": None, "stats": {}}

        # Count stocks by change
        cur.execute(
            "SELECT code, close, "
            "(SELECT close FROM daily_kline k2 WHERE k2.code = k1.code AND k2.date < k1.date ORDER BY k2.date DESC LIMIT 1) as prev_close "
            "FROM daily_kline k1 WHERE k1.date = ?",
            (latest,),
        )
        rows = cur.fetchall()
        up = sum(1 for r in rows if r[1] and r[2] and r[1] > r[2])
        down = sum(1 for r in rows if r[1] and r[2] and r[1] < r[2])
        flat = len(rows) - up - down

        return {
            "latest_date": latest,
            "stats": {
                "total": len(rows),
                "up": up,
                "down": down,
                "flat": flat,
            },
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Trade History (交易记录)
# ---------------------------------------------------------------------------

@router.get("/trades")
def get_trades() -> list:
    """Return trade history from paper trading state."""
    state = _read_json(_PAPER_DIR / "paper_trading_state.json")
    return state.get("history", [])


@router.get("/trades/v5")
def get_trades_v5() -> list:
    """Return V5 trade history."""
    state = _read_json(_PAPER_DIR / "paper_trading_state_v2.json")
    return state.get("history", [])


def register_trading_tools_routes(app, require_auth=None):
    """Register trading tools routes on the FastAPI app."""
    dependencies = []
    if require_auth is not None:
        from fastapi import Depends
        dependencies = [Depends(require_auth)]

    # Override router dependencies if auth is required
    if dependencies:
        for route in router.routes:
            if hasattr(route, "dependencies"):
                route.dependencies = dependencies

    app.include_router(router)

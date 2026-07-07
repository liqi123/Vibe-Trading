"""API routes for custom trading tools.

Provides endpoints for:
- Expectation management (预期管理)
- Paper trading positions (模拟盘)
- Daily scan results (每日选股)
- Market sentiment (市场情绪)
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends

_log = logging.getLogger("trading_tools")

# Resolve the project root (trading/) relative to this file's location
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8899")
_DB_PATH = _PROJECT_ROOT / "tdx_data.db"
_PAPER_DIR = _PROJECT_ROOT / "paper"

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


def _stock_table() -> str:
    """Auto-detect stocks / stock_names table (delegates to utils.db)."""
    try:
        from utils.db import stock_name_table
        return stock_name_table()
    except Exception:
        return 'stocks'


def _get_db() -> sqlite3.Connection | None:
    """Open the SQLite database if it exists."""
    # Try config DB path first (project convention: from utils.config import DB_PATH)
    try:
        from utils.config import DB_PATH
        if Path(str(DB_PATH)).exists():
            return sqlite3.connect(str(DB_PATH))
    except Exception:
        _log.warning("_get_db: config DB_PATH failed, falling back to _DB_PATH", exc_info=True)
    # Fallback to project root path
    if _DB_PATH.exists():
        return sqlite3.connect(str(_DB_PATH))
    return None


def _latest_trade_date(db: sqlite3.Connection) -> str | None:
    """Get the latest trading date from daily_kline."""
    try:
        cur = db.cursor()
        cur.execute("SELECT DISTINCT date FROM daily_kline ORDER BY date DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _ma(arr: list[float], period: int) -> float:
    """Simple moving average."""
    if not arr:
        return 0
    n = min(len(arr), period)
    return round(sum(arr[-n:]) / n, 2)
def _local_extrema(high_arr, low_arr, date_arr, lookback=5):
    """Find local highs and lows.
    
    Returns list of tuples: (index, value, date_string)
    """
    n = len(high_arr)
    high_extrema = []
    low_extrema = []
    
    for i in range(1, n - 1):
        start = max(0, i - lookback)
        end = min(n, i + lookback + 1)
        if all(high_arr[i] >= h for h in high_arr[start:end] if h != high_arr[i]):
            high_extrema.append((i, high_arr[i], str(date_arr[i])))
        if all(low_arr[i] <= l for l in low_arr[start:end] if l != low_arr[i]):
            low_extrema.append((i, low_arr[i], str(date_arr[i])))
    
    return high_extrema, low_extrema


def _load_industry_map() -> dict:
    """Load industry mapping, returns {} on failure."""
    try:
        from utils.sector_utils import get_industry_map
        return get_industry_map()
    except Exception:
        _log.warning("failed to load industry map", exc_info=True)
        return {}


# ---------------------------------------------------------------------------
# Expectation Management (预期管理)
# ---------------------------------------------------------------------------

@router.get("/expectations")
def get_expectations() -> dict:
    """Return expectation state for all positions, with live prev_close from DB."""
    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    if not positions:
        return state

    db = _get_db()
    if db is None:
        return state
    try:
        from utils.config import get_date_col
        date_col, _ = get_date_col()
        for p in positions:
            row = db.execute(
                f"SELECT close FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 1",
                (p["code"],)
            ).fetchone()
            if row and row[0]:
                p["prev_close"] = row[0]
    finally:
        db.close()
    return state


@router.get("/expectations/sentiment")
def get_sentiment() -> dict:
    """Return market sentiment state."""
    return _read_json(_PAPER_DIR / "market_sentiment_state.json")


@router.get("/expectations/search")
def search_stock(q: str = "") -> dict:
    """Search stocks by code or name. Returns top 10 matches."""
    if not q or len(q) < 1:
        return {"results": []}

    db = _get_db()
    if db is None:
        return {"results": []}
    try:
        cur = db.cursor()
        q_upper = q.upper()
        # Search by code (with/without prefix) or name (fuzzy)
        cur.execute(
            f"SELECT code, name FROM {_stock_table()} "
            "WHERE code LIKE ? OR UPPER(code) LIKE ? OR name LIKE ? "
            "LIMIT 10",
            (f"%{q}%", f"%{q_upper}%", f"%{q}%"),
        )
        rows = cur.fetchall()
        return {"results": [{"code": r[0], "name": r[1]} for r in rows]}
    finally:
        db.close()


@router.post("/expectations/add")
def add_expectation(data: dict):
    """Add a stock to expectations. Accepts code or name."""
    raw = data.get("code", "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Code required")

    # Normalize code: if pure digits, add market prefix
    code = raw.lower()
    if code.isdigit():
        code = ("sh" if code.startswith("6") else "sz") + code
    elif not code.startswith(("sh", "sz")):
        # Might be a name — search DB for it
        db = _get_db()
        if db:
            try:
                cur = db.cursor()
                cur.execute(f"SELECT code, name FROM {_stock_table()} WHERE name LIKE ? LIMIT 1", (f"%{raw}%",))
                row = cur.fetchone()
                if row:
                    code = row[0]
            finally:
                db.close()

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])

    # Check duplicate (normalize stored codes too)
    for p in positions:
        stored = p.get("code", "").lower()
        if stored == code or stored.lstrip("shsz") == code.lstrip("shsz"):
            return {"ok": True, "message": "Already exists"}

    # Get stock name from DB
    name = ""
    prev_close = 0
    db = _get_db()
    if db:
        try:
            cur = db.cursor()
            cur.execute(f"SELECT name FROM {_stock_table()} WHERE code = ?", (code,))
            row = cur.fetchone()
            if row:
                name = row[0]
        finally:
            db.close()

    # Fallback: get from Tencent API
    if not name:
        try:
            from utils.tencent_quotes import fetch_detail
            q = fetch_detail([code]).get(code, {})
            name = q.get("name", "")
            prev_close = q.get("prev_close", 0)
        except Exception:
            _log.warning("add_expectation: Tencent fallback failed for %s", code)

    positions.append({
        "code": code,
        "name": name,
        "prev_close": prev_close,
        "status": "关注中",
    })
    state["positions"] = positions

    (_PAPER_DIR / "expectation_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.post("/expectations/update-prices")
def update_expectation_prices(data: dict):
    """Update E price, X price and runaway price for a stock."""
    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])

    for p in positions:
        if p.get("code") == code:
            p["e_price"] = data.get("e_price", 0)
            p["x_price"] = data.get("x_price", 0)
            p["runaway_price"] = data.get("runaway_price", 0)
            break

    state["positions"] = positions
    (_PAPER_DIR / "expectation_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.post("/expectations/remove")
def remove_expectation(data: dict):
    """Remove a stock from expectations."""
    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    state["positions"] = [p for p in positions if p.get("code") != code]

    (_PAPER_DIR / "expectation_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.post("/expectations/collect-auction")
def collect_auction():
    """Collect auction data for all expectation stocks via Tencent API.
    
    Before 09:30: fetch live from Tencent. After 09:30: read from auction table.
    """
    from utils.tencent_quotes import fetch_detail, add_prefix

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    if not positions:
        return {"stocks": []}

    codes = [p["code"] for p in positions if p.get("code")]
    if not codes:
        return {"stocks": []}

    blocked, _ = _check_auction_time()
    if blocked:
        try:
            db = _get_db()
            if db:
                cur = db.cursor()
                today_str = date.today().isoformat()
                results = []
                for code in codes:
                    bare = code[2:] if code.startswith(("sh", "sz", "bj")) else code
                    row = cur.execute(
                        "SELECT auction_vol, auction_price, open_price FROM auction WHERE date=? AND (code=? OR code=?)",
                        (today_str, code, bare)
                    ).fetchone()
                    if row:
                        auction_price = row[1] or 0
                        open_price = row[2] or 0
                        change_pct = round((auction_price - open_price) / open_price * 100, 2) if open_price else 0
                        results.append({
                            "code": code,
                            "auction_price": auction_price,
                            "auction_change_pct": change_pct,
                            "today_vol": row[0],
                            "prev_vol": 0,
                            "vol_ratio": 0,
                        })
                db.close()
                if results:
                    return {"stocks": results, "status": "exists"}
        except Exception:
            pass
        return {"stocks": [], "status": "no_data"}

    data = fetch_detail(codes)
    results = []
    for raw_code, q in data.items():
        code = add_prefix(raw_code)
        vol_ratio = q["prev_volume"] > 0 and q["volume"] > 0 and q["volume"] / q["prev_volume"] or 0
        results.append({
            "code": code,
            "name": q["name"],
            "auction_price": q["price"],
            "auction_change_pct": q["change_pct"],
            "today_vol": int(q["volume"]),
            "prev_vol": q["prev_volume"],
            "vol_ratio": round(vol_ratio, 2),
        })

    return {"stocks": results}


@router.post("/expectations/save-auction")
def save_auction(data: dict):
    """Save manual auction volume edits."""
    code = data.get("code", "").strip().lower()
    today_vol = data.get("today_vol", 0)
    prev_vol = data.get("prev_vol", 0)

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    auction_data = state.get("auction_data", {})
    auction_data[code] = {
        "today_vol": today_vol,
        "prev_vol": prev_vol,
    }
    state["auction_data"] = auction_data

    (_PAPER_DIR / "expectation_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Paper Trading (模拟盘)
# ---------------------------------------------------------------------------

@router.get("/portfolio")
def get_portfolio() -> dict:
    """Return V1 paper trading state (Fibonacci strategy) with live prices."""
    path = _PAPER_DIR / "paper_trading_state.json"
    try:
        from utils.paper_trading import load_state
        state = load_state(path)
    except Exception:
        state = _read_json(path)
    # Sort history newest first
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state


@router.get("/portfolio/v5")
def get_portfolio_v5() -> dict:
    """Return V5 paper trading state (trend strategy) with live prices."""
    path = _PAPER_DIR / "paper_trading_state_v2.json"
    try:
        from utils.paper_trading import load_state
        state = load_state(path)
    except Exception:
        state = _read_json(path)
    # Sort history newest first
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state


@router.get("/scan-results")
def get_scan_results(strategy: str = "fibonacci", date: str = "") -> dict:
    """Return cached scan results for given strategy and date."""
    if not date:
        from datetime import date as _date
        date = _date.today().strftime("%Y-%m-%d")
    prefix = "v1" if strategy == "fibonacci" else "v5"
    path = _PAPER_DIR / f"{prefix}_screening_cache_{date}.json"
    try:
        raw = _read_json(path)
        if not raw:
            return {"date": date, "candidates": [], "message": "no cache found"}
        # Normalize: V5 cache uses "results", unify to "candidates"
        if "candidates" not in raw and "results" in raw:
            raw["candidates"] = raw.pop("results")
        return raw
    except Exception:
        return {"date": date, "candidates": [], "message": "no cache found"}


@router.get("/runaway-price")
def api_runaway_price(code: str = "", date: str = "") -> dict:
    """Calculate runaway price for a stock on a date."""
    if not code or not date:
        raise HTTPException(status_code=400, detail="code and date required")
    code = code.strip().lower()
    date = date.strip()

    # Auto-add market prefix if missing
    if not code.startswith(("sh", "sz")):
        if code.startswith(("6", "9")):
            code = "sh" + code
        elif code.startswith(("0", "3")):
            code = "sz" + code

    # Try runaway_price module first
    try:
        from utils.runaway_price import calc_runaway_price
        result = calc_runaway_price(code, date)
        if result:
            return result
    except Exception:
        _log.warning("calc_runaway_price failed for %s on %s", code, date)

    # Fallback: query DB directly, handle mixed date formats
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        date_int = int(date.replace("-", ""))
        # Try both string and integer date formats
        row = db.execute(
            "SELECT open, high, low, close FROM daily_kline WHERE code=? AND (date=? OR trade_date=?)",
            (code, date, date_int),
        ).fetchone()
        if row:
            o, h, l, c = row
            return {
                "code": code, "date": date,
                "open": o, "high": h, "low": l, "close": c,
                "runaway_price": round((h + l + o + c) / 4, 3),
            }
    finally:
        db.close()
    raise HTTPException(status_code=404, detail=f"No data for {code} on {date}")


@router.post("/portfolio/update-field")
def update_position_field(data: dict):
    """Update a single field of a position.

    Expects: {code, portfolio: "v1"|"v5", field, value}
    """
    code = data.get("code", "").strip().lower()
    portfolio = data.get("portfolio", "v5")
    field = data.get("field", "")
    value = data.get("value")

    if not code or not field:
        raise HTTPException(status_code=400, detail="Code and field required")

    state_file = "paper_trading_state.json" if portfolio == "v1" else "paper_trading_state_v2.json"
    path = _PAPER_DIR / state_file
    state = _read_json(path)
    positions = state.get("positions", [])

    for p in positions:
        if p.get("code") == code:
            p[field] = value
            break
    else:
        raise HTTPException(status_code=404, detail=f"No position for {code}")

    state["positions"] = positions
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@router.post("/portfolio/sell")
def sell_position(data: dict):
    """Sell a position from paper trading.

    Expects: {code, portfolio: "v1"|"v5", shares?, reason?}
    """
    code = data.get("code", "").strip().lower()
    portfolio = data.get("portfolio", "v5")
    shares = data.get("shares")  # None means sell all
    reason = data.get("reason", "手动卖出")

    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state_file = "paper_trading_state.json" if portfolio == "v1" else "paper_trading_state_v2.json"
    path = _PAPER_DIR / state_file
    state = _read_json(path)
    positions = state.get("positions", [])

    # Find position
    pos = None
    for p in positions:
        if p.get("code") == code:
            pos = p
            break
    if not pos:
        raise HTTPException(status_code=404, detail=f"No position for {code}")

    sell_shares = shares if shares else pos.get("shares", 0)
    if sell_shares <= 0:
        raise HTTPException(status_code=400, detail="Invalid shares")

    buy_price = pos.get("buy_price", 0)
    # Get current price from Tencent
    current_price = pos.get("current_price", buy_price)
    try:
        from utils.tencent_quotes import get_prices
        prices = get_prices([code])
        if code in prices:
            current_price = prices[code]
    except Exception:
        _log.warning("sell_position: get_prices failed for %s", code)

    pnl = (current_price - buy_price) * sell_shares
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0

    today = date.today().strftime("%Y-%m-%d")

    # Add to history
    history = state.get("history", [])
    history.append({
        "date": today,
        "action": "sell",
        "code": code,
        "name": pos.get("name", ""),
        "price": current_price,
        "shares": sell_shares,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "note": reason,
    })
    state["history"] = history

    # Update or remove position
    remaining = pos.get("shares", 0) - sell_shares
    if remaining <= 0:
        state["positions"] = [p for p in positions if p.get("code") != code]
    else:
        for p in positions:
            if p.get("code") == code:
                p["shares"] = remaining
                p["cost"] = buy_price * remaining
                break

    # Update cash
    state["cash"] = state.get("cash", 0) + current_price * sell_shares

    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "pnl": round(pnl, 2), "price": current_price}


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
        from utils.config import get_date_col
        date_col, is_int = get_date_col()
        cur = db.cursor()
        # Get latest kline
        cur.execute(
            f"SELECT {date_col}, open, high, low, close, volume FROM daily_kline "
            f"WHERE code = ? ORDER BY {date_col} DESC LIMIT 30",
            (code,),
        )
        rows = cur.fetchall()
        # Get stock name
        cur.execute(f"SELECT name FROM {_stock_table()} WHERE code = ?", (code,))
        name_row = cur.fetchone()
        def _fmt(d):
            s = str(d)
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if is_int else s
        return {
            "code": code,
            "name": name_row[0] if name_row else "",
            "kline": [
                {"date": _fmt(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows
            ],
        }
    finally:
        db.close()


@router.post("/stock/{code}/buy")
def buy_stock(code: str, data: dict):
    """Buy a stock into paper trading portfolio.

    Expects: {strategy: "fibonacci"|"v5", name, price, score?, E?, stop?, ...}
    """
    strategy = data.get("strategy", "fibonacci")
    state_file = "paper_trading_state.json" if strategy == "fibonacci" else "paper_trading_state_v2.json"
    path = _PAPER_DIR / state_file
    state = _read_json(path)
    if not state:
        state = {"initial_capital": 200000, "cash": 200000, "positions": [], "history": []}

    # Check if already held
    if any(p.get("code") == code for p in state.get("positions", [])):
        return {"success": False, "message": "已持仓"}

    # Check max positions (5)
    if len(state.get("positions", [])) >= 5:
        return {"success": False, "message": "持仓已达上限(5只)"}

    from utils.config import INITIAL_CAPITAL, COMMISSION, SLIPPAGE

    layer_divisor = 6
    layer = state.get("initial_capital", INITIAL_CAPITAL) / layer_divisor
    buy_amount = min(layer, state["cash"] - layer)
    if buy_amount <= 0:
        return {"success": False, "message": "现金不足"}

    price = data.get("price", 0)
    if price <= 0:
        return {"success": False, "message": "无效价格"}

    shares = int(buy_amount / price / 100) * 100
    if shares <= 0:
        return {"success": False, "message": "股数不足(最少100股)"}

    buy_price_adj = price * (1 + SLIPPAGE)
    total_cost = shares * buy_price_adj * (1 + COMMISSION)

    name = data.get("name", "")
    state["cash"] -= total_cost

    if strategy == "fibonacci":
        pos = {
            "code": code, "name": name,
            "buy_price": buy_price_adj, "shares": shares, "cost": total_cost,
            "current_price": buy_price_adj,
            "E": data.get("E", 0), "stop": data.get("stop", 0),
        }
    else:  # v5
        score = data.get("score", 0)
        pos = {
            "code": code, "name": name,
            "buy_price": buy_price_adj, "shares": shares, "cost": total_cost,
            "current_price": buy_price_adj,
            "highest": buy_price_adj, "score": score,
        }

    state.setdefault("positions", []).append(pos)
    today = date.today().strftime("%Y-%m-%d")
    state.setdefault("history", []).append({
        "date": today, "action": "buy",
        "code": code, "name": name,
        "price": buy_price_adj, "shares": shares,
    })

    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "success": True, "message": f"买入 {name} {code}: {shares}股 @{buy_price_adj:.2f}",
            "shares": shares, "price": buy_price_adj, "cost": total_cost,
        }
    except Exception as e:
        return {"success": False, "message": f"保存失败: {e}"}


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
        from utils.config import get_date_col
        date_col, _ = get_date_col()

        cur = db.cursor()
        cur.execute(f"SELECT MAX({date_col}) FROM daily_kline")
        latest = cur.fetchone()[0]
        if not latest:
            return {"latest_date": None, "stats": {}}

        latest_str = str(latest) if isinstance(latest, int) else latest

        # Get the two latest dates for fast join
        cur.execute(f"SELECT DISTINCT {date_col} FROM daily_kline ORDER BY {date_col} DESC LIMIT 2")
        dates = [r[0] for r in cur.fetchall()]
        if len(dates) < 2:
            return {"latest_date": latest_str, "stats": {"total": 0, "up": 0, "down": 0, "flat": 0}}

        cur.execute(
            f"SELECT a.code, a.close, b.close as prev_close "
            f"FROM daily_kline a JOIN daily_kline b ON a.code = b.code "
            f"WHERE a.{date_col} = ? AND b.{date_col} = ?",
            (dates[0], dates[1]),
        )
        rows = cur.fetchall()
        up = sum(1 for r in rows if r[1] and r[2] and r[1] > r[2])
        down = sum(1 for r in rows if r[1] and r[2] and r[1] < r[2])
        flat = len(rows) - up - down

        return {
            "latest_date": latest_str,
            "stats": {"total": len(rows), "up": up, "down": down, "flat": flat},
        }
    finally:
        db.close()


_market_cache: dict | None = None
_market_cache_time: float = 0
MARKET_CACHE_TTL = 30  # seconds


@router.get("/market/realtime")
def get_market_realtime() -> dict:
    """Real-time market advance/decline stats via Tencent API (cached 30s)."""
    global _market_cache, _market_cache_time
    now = time.time()
    if _market_cache is not None and now - _market_cache_time < MARKET_CACHE_TTL:
        return _market_cache

    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        cur.execute(f"SELECT code FROM {_stock_table()} WHERE code LIKE 'sh60%' OR code LIKE 'sz00%' OR code LIKE 'sz30%'")
        codes_raw = [r[0] for r in cur.fetchall()]
    finally:
        db.close()

    from utils.tencent_quotes import fetch_detail

    up = down = flat = limit_up = limit_down = 0
    if codes_raw:
        quotes = fetch_detail(codes_raw)
        for full_code, q in quotes.items():
            chg = q["change_pct"]
            if chg > 0:
                up += 1
            elif chg < 0:
                down += 1
            else:
                flat += 1
            price = q["price"]
            prev_close = q["prev_close"]
            if prev_close > 0 and price > 0:
                actual_pct = (price - prev_close) / prev_close
                threshold = 0.198 if full_code.startswith(("sh68", "sz30")) else 0.098
                if actual_pct >= threshold:
                    limit_up += 1
                elif actual_pct <= -threshold:
                    limit_down += 1

    result = {
        "up": up, "down": down, "flat": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "total": up + down + flat,
        "_cached": _market_cache is not None,
    }
    _market_cache = result
    _market_cache_time = now
    return result


# ---------------------------------------------------------------------------
# Market Momentum (市场动量)
# ---------------------------------------------------------------------------

# 行业板块指数代码（sz3992xx）
_SECTOR_CODES_FULL = [
    ("sz399231", "农林牧渔"), ("sz399232", "采矿"), ("sz399233", "制造"),
    ("sz399234", "水电燃气"), ("sz399235", "建筑"), ("sz399236", "批发零售"),
    ("sz399237", "交通运输"), ("sz399238", "餐饮住宿"), ("sz399239", "信息技术"),
    ("sz399240", "金融"), ("sz399241", "房地产"), ("sz399242", "商务服务"),
    ("sz399243", "科研服务"), ("sz399244", "公共管理"), ("sz399248", "文化体育"),
    ("sz399274", "汽车"), ("sz399275", "医药生物"), ("sz399276", "机械设备"),
    ("sz399277", "电子"), ("sz399278", "国防军工"), ("sz399279", "通信"),
    ("sz399280", "计算机"), ("sz399281", "传媒"), ("sz399282", "有色金属"),
    ("sz399283", "基础化工"), ("sz399284", "钢铁"), ("sz399285", "建筑材料"),
    ("sz399286", "食品饮料"), ("sz399287", "纺织服装"), ("sz399288", "公用事业"),
]
_SECTOR_CODES_SUBSET = _SECTOR_CODES_FULL[:15]  # 无后15个较新板块索引，更稳健

def _fetch_sector_momentum(sector_codes: list[tuple[str, str]]) -> list[dict]:
    """Fetch sector momentum from Tencent, returns [{name, momentum}]."""
    from utils.tencent_quotes import fetch_raw
    codes = [c for c, _ in sector_codes]
    raw = fetch_raw(codes, min_fields=33)
    sectors = []
    for code, fields in raw.items():
        try:
            change_pct = float(fields[32])
        except (ValueError, IndexError):
            continue
        name = next((n for c, n in sector_codes if c == code), fields[1])
        sectors.append({"name": name, "momentum": round(change_pct, 1)})
    sectors.sort(key=lambda x: x["momentum"], reverse=True)
    return sectors


_MOMENTUM_CACHE: dict | None = None
_MOMENTUM_CACHE_TIME: float = 0
_MOMENTUM_CACHE_TTL = 60

@router.get("/market/momentum")
def get_market_momentum() -> dict:
    """市场动量 — 板块排名 + 均线/RSI 分布

    Returns:
        {sectors: [{name, momentum, rank}], ma_distribution: {above5, above10, above20, total},
         rsi_distribution: {oversold, neutral, overbought}}
    """
    global _MOMENTUM_CACHE, _MOMENTUM_CACHE_TIME
    now = time.time()
    if _MOMENTUM_CACHE is not None and now - _MOMENTUM_CACHE_TIME < _MOMENTUM_CACHE_TTL:
        return _MOMENTUM_CACHE

    db = _get_db()
    if db is None:
        return {"error": "数据库不可用"}
    try:
        from utils.config import get_date_col, fmt_date
        date_col, _ = get_date_col()
        cur = db.cursor()

        # 获取最新日期
        cur.execute(f"SELECT MAX({date_col}) FROM daily_kline")
        latest = cur.fetchone()[0]
        if not latest:
            return {"error": "无数据"}

        # ---- 板块动量（Tencent 行业指数） ----
        sectors = _fetch_sector_momentum(_SECTOR_CODES_FULL)
        top5 = [{"name": s["name"], "momentum": s["momentum"], "rank": i+1} for i, s in enumerate(sectors[:5])]
        bottom5 = [{"name": s["name"], "momentum": s["momentum"], "rank": len(sectors)-i} for i, s in enumerate(sectors[-5:])]

        # ---- MA 分布（最近收盘 vs N日前） ----
        ma_result = {"above5": 0, "above10": 0, "above20": 0, "total": 0}
        try:
            # 获取所有股票最新收盘价和前N日收盘价
            dates = [r[0] for r in cur.execute(
                f"SELECT DISTINCT {date_col} FROM daily_kline ORDER BY {date_col} DESC LIMIT 22"
            ).fetchall()]
            if len(dates) >= 2:
                today = dates[0]
                d5 = dates[4] if len(dates) > 4 else dates[-1]
                d10 = dates[9] if len(dates) > 9 else dates[-1]
                d20 = dates[20] if len(dates) > 20 else dates[-1]

                cur.execute(
                    f"SELECT a.close, b.close, c.close, d.close "
                    f"FROM daily_kline a "
                    f"LEFT JOIN daily_kline b ON a.code=b.code AND b.{date_col}=? "
                    f"LEFT JOIN daily_kline c ON a.code=c.code AND c.{date_col}=? "
                    f"LEFT JOIN daily_kline d ON a.code=d.code AND d.{date_col}=? "
                    f"WHERE a.{date_col}=?",
                    (d5, d10, d20, today),
                )
                rows = cur.fetchall()
                ma_result = {
                    "above5": sum(1 for r in rows if r[0] and r[1] and r[0] > r[1]),
                    "above10": sum(1 for r in rows if r[0] and r[2] and r[0] > r[2]),
                    "above20": sum(1 for r in rows if r[0] and r[3] and r[0] > r[3]),
                    "total": len(rows),
                }
        except Exception:
            _log.warning("get_market_momentum: MA distribution failed", exc_info=True)

        # ---- RSI 分布 ----
        rsi_result = {"oversold": 0, "normal": 0, "overbought": 0}
        try:
            # 简化：用 N日涨跌幅 代替 RSI 估算
            # 跌>10% = oversold, 涨>10% = overbought
            if len(dates) >= 14:
                d14 = dates[13] if len(dates) > 13 else dates[-1]
                cur.execute(
                    f"SELECT a.close, b.close FROM daily_kline a "
                    f"JOIN daily_kline b ON a.code=b.code AND b.{date_col}=? "
                    f"WHERE a.{date_col}=?",
                    (d14, today),
                )
                rows = cur.fetchall()
                oversold = normal = overbought = 0
                for r in rows:
                    if r[0] and r[1] and r[1] > 0:
                        pct = (r[0] / r[1] - 1) * 100
                        if pct <= -10:
                            oversold += 1
                        elif pct >= 10:
                            overbought += 1
                        else:
                            normal += 1
                rsi_result = {"oversold": oversold, "normal": normal, "overbought": overbought}
        except Exception:
            _log.warning("get_market_momentum: RSI distribution failed", exc_info=True)

        # ---- 涨跌停结构（今日/昨日对比） ----
        struct = {}
        try:
            for limit_dir in ["up", "down"]:
                limit_pct = 9.8 if limit_dir == "up" else -9.8
                op = ">=" if limit_dir == "up" else "<="
                cur.execute(
                    f"SELECT a.close, b.close FROM daily_kline a "
                    f"JOIN daily_kline b ON a.code=b.code AND b.{date_col}=? "
                    f"WHERE a.{date_col}=? AND b.close > 0 "
                    f"AND (a.close - b.close)/b.close*100 {op} ?",
                    (dates[1] if len(dates) > 1 else today, today, limit_pct),
                )
                limit_count = len(cur.fetchall())
                struct[f"limit_{limit_dir}"] = limit_count
        except Exception:
            _log.warning("get_market_momentum: structure calculation failed", exc_info=True)

        result = {
            "sectors": {"top": top5, "bottom": bottom5},
            "ma_distribution": ma_result,
            "rsi_distribution": rsi_result,
            "structure": struct,
        }
        _MOMENTUM_CACHE = result
        _MOMENTUM_CACHE_TIME = now
        return result
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Market Sentiment (市场情绪)
# ---------------------------------------------------------------------------

@router.get("/market/sentiment")
def get_market_sentiment() -> dict:
    """市场情绪 — 情绪周期 + 涨跌比 + 情绪评分

    Returns:
        {cycle: "up"|"down"|"unknown", cycle_updated: str,
         advance_decline_ratio: float, limit_ratio: float,
         sentiment_score: int (0-100), label: str}
    """
    db = _get_db()
    if db is None:
        return {"error": "数据库不可用"}
    try:
        from utils.config import get_date_col
        date_col, _ = get_date_col()
        cur = db.cursor()

        # 最新两日
        cur.execute(f"SELECT DISTINCT {date_col} FROM daily_kline ORDER BY {date_col} DESC LIMIT 2")
        dates = [r[0] for r in cur.fetchall()]
        if len(dates) < 2:
            return {"cycle": "unknown", "sentiment_score": 50, "label": "数据不足"}

        today, prev = dates[0], dates[1]
        cur.execute(
            f"SELECT a.close, b.close FROM daily_kline a "
            f"JOIN daily_kline b ON a.code=b.code AND b.{date_col}=? "
            f"WHERE a.{date_col}=?",
            (prev, today),
        )
        rows = cur.fetchall()
        total = len(rows)
        up = sum(1 for r in rows if r[0] and r[1] and r[0] > r[1])
        down = sum(1 for r in rows if r[0] and r[1] and r[0] < r[1])
        flat = total - up - down

        # 涨跌比
        ad_ratio = round(up / down, 2) if down > 0 else 99

        # 涨停/跌停
        limit_up = sum(1 for r in rows if r[0] and r[1] and r[1] > 0 and (r[0]-r[1])/r[1] >= 0.098)
        limit_down = sum(1 for r in rows if r[0] and r[1] and r[1] > 0 and (r[0]-r[1])/r[1] <= -0.098)
        limit_ratio = round(limit_up / limit_down, 2) if limit_down > 0 else 99

        # 情绪周期（从文件读取）
        cycle = "unknown"
        cycle_updated = ""
        try:
            state = _read_json(_PAPER_DIR / "market_sentiment_state.json")
            cycle = state.get("cycle", "unknown")
            cycle_updated = state.get("updated_at", "")
        except Exception:
            _log.warning("get_market_sentiment: failed to read sentiment state file")

        # 情绪评分 (0-100)
        score = 50
        # 涨跌比贡献 (0-40): ad_ratio >= 2 -> +20, ad_ratio >= 1 -> +10, ad_ratio <= 0.5 -> -20
        if total > 0:
            up_pct = up / total * 100
            score += min(20, max(-20, (up_pct - 50) * 1.5))
        # 涨跌比额外贡献
        score += 5 if ad_ratio >= 2 else (-5 if ad_ratio <= 0.5 else 0)
        # 涨停跌停比贡献
        score += 10 if limit_ratio >= 3 else (5 if limit_ratio >= 1.5 else (-5 if limit_ratio <= 0.5 else 0))
        # 情绪周期修正
        score += 10 if cycle == "up" else (-10 if cycle == "down" else 0)
        score = max(0, min(100, int(score)))

        # 标签
        if score >= 75:
            label = "乐观 😊"
        elif score >= 60:
            label = "偏暖 🙂"
        elif score >= 40:
            label = "中性 😐"
        elif score >= 25:
            label = "偏冷 🥶"
        else:
            label = "恐慌 😱"

        return {
            "cycle": cycle,
            "cycle_updated": cycle_updated,
            "date": str(today),
            "total": total,
            "up": up, "down": down, "flat": flat,
            "advance_decline_ratio": ad_ratio,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "limit_ratio": limit_ratio,
            "sentiment_score": score,
            "label": label,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Prices (行情代理，解决浏览器CORS)
# ---------------------------------------------------------------------------

@router.get("/prices")
def get_prices(codes: str = "") -> dict:
    from utils.tencent_quotes import add_prefix, fetch_detail

    if not codes:
        return {"prices": {}}
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return {"prices": {}}

    results = {}
    for i in range(0, len(code_list), 50):
        batch = [add_prefix(c) for c in code_list[i:i+50]]
        try:
            quotes = fetch_detail(batch)
            for full_code, q in quotes.items():
                results[full_code] = {
                    "name": q["name"],
                    "price": q["price"],
                    "change_pct": q["change_pct"],
                    "prev_close": q["prev_close"],
                    "open": q["open"],
                    "high": q["high"],
                    "low": q["low"],
                    "volume": q["volume"],
                }
        except Exception:
            continue
    return {"prices": results}


# ---------------------------------------------------------------------------
# Update Data (数据更新)
# ---------------------------------------------------------------------------

@router.post("/update-data")
def update_data():
    """Trigger data update (TDX zip or Tencent fallback).

    Returns {ok, method, message}.
    """
    # Try TDX zip first
    tdx_script = _PROJECT_ROOT / "tdx_utils" / "update_tdx_daily.py"
    if tdx_script.exists():
        try:
            result = subprocess.run(
                ["python", str(tdx_script)],
                capture_output=True, text=True, timeout=600,
                cwd=str(_PROJECT_ROOT),
            )
            stdout = result.stdout or ""
            if result.returncode == 0 and "处理完成" in stdout:
                return {"ok": True, "method": "tdx_zip", "message": stdout.strip().split("\n")[-1]}
            # Fallback to Tencent
        except subprocess.TimeoutExpired:
            _log.warning("update_data: TDX zip timed out")
        except Exception:
            _log.warning("update_data: TDX zip failed", exc_info=True)

    # Fallback: Tencent via utils.update
    try:
        from utils.update import step_tencent
        from utils.db import connect_db
        from utils.config import get_date_col
        conn = connect_db()
        date_col, is_int = get_date_col()
        total = step_tencent(conn, date_col, is_int)
        conn.close()
        return {"ok": True, "method": "tencent", "message": f"Tencent fallback completed: {total} rows"}
    except Exception as e:
        _log.warning("Tencent fallback failed: %s", e)

    return {"ok": False, "method": "none", "message": "No update script found or all methods failed"}


# ---------------------------------------------------------------------------
# Trade History (交易记录)
# ---------------------------------------------------------------------------

@router.post("/run-script")
def run_script(data: dict):
    """Run a trading script in background thread, return task id."""
    script = data.get("script", "")
    scripts = {
        "fibonacci": "strategies/daily_check.py",
        "v5": "strategies/daily_check_v5.py",
        "stops": "-m utils stops",
        "review": "reports/generate_review.py",
        "review_v5": "reports/generate_review.py",
    }
    if script not in scripts:
        raise HTTPException(status_code=400, detail=f"Unknown script: {script}")

    task_id = str(uuid.uuid4())[:8]
    cmd = scripts[script]
    output_file = _PAPER_DIR / f"script_output_{task_id}.txt"

    ts_start = datetime.now()

    # 安全处理参数
    if cmd.startswith("-m"):
        args = ["python"] + cmd.split()[1:]
    else:
        args = ["python", cmd]

    # 验证脚本路径安全
    script_path = _PROJECT_ROOT / cmd if not cmd.startswith("-m") else None
    if script_path and not script_path.exists():
        output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: 脚本文件不存在\n", encoding="utf-8")
        return {"task_id": task_id}

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # 初始内容：前端靠"执行中"判断任务是否活跃
    output_file.write_text(f"[{ts_start.strftime('%H:%M:%S')}] 执行中...\n", encoding="utf-8")

    def _run():
        try:
            safe_args = ["python", "-X", "utf8"] + args[1:]
            proc = subprocess.Popen(
                safe_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
                env=env,
                bufsize=1,
                executable=None,
            )
            lines = []
            for line in iter(proc.stdout.readline, b''):
                text = line.decode("utf-8", errors="replace")
                lines.append(text)
                # 保持"执行中"前缀，让前端知道任务还在跑
                content = f"[{ts_start.strftime('%H:%M:%S')}] 执行中...\n" + "".join(lines)
                output_file.write_text(content, encoding="utf-8")
            proc.stdout.close()
            proc.wait(timeout=10)
            ts = datetime.now().strftime("%H:%M:%S")
            # 去除"执行中"前缀，写入最终结果
            content = "".join(lines) + f"\n[{ts}] 执行完成 (exit={proc.returncode})\n"
            output_file.write_text(content, encoding="utf-8")
        except FileNotFoundError as e:
            output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: 找不到可执行文件 - {str(e)[:200]}\n", encoding="utf-8")
        except Exception as e:
            try:
                existing = output_file.read_text(encoding="utf-8")
            except Exception:
                existing = ""
            output_file.write_text(existing + f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {str(e)[:200]}\n", encoding="utf-8")

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/run-script/{task_id}")
def get_script_output(task_id: str):
    """Get script execution output."""
    output_file = _PAPER_DIR / f"script_output_{task_id}.txt"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    content = output_file.read_text(encoding="utf-8")
    is_running = "执行完成" not in content and "超时" not in content and "错误:" not in content
    return {"output": content, "status": "running" if is_running else "completed"}


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


@router.get("/watchlist-auction")
def get_watchlist_auction(codes: str = "") -> dict:
    """Return auction data + yesterday volume for watchlist stocks."""
    if not codes:
        return {"auction": {}}
    code_list = [c.strip().lower() for c in codes.split(",") if c.strip()]
    if not code_list:
        return {"auction": {}}

    db = _get_db()
    if db is None:
        return {"auction": {}}
    try:
        dates = [r[0] for r in db.execute(
            "SELECT DISTINCT date FROM auction ORDER BY date DESC LIMIT 2"
        ).fetchall()]
        if not dates:
            return {"auction": {}}

        today_date = dates[0]
        prev_date = dates[1] if len(dates) > 1 else None

        # Auction table stores codes without sh/sz prefix (mostly),
        # but some dates have mixed formats (both bare and prefixed)
        bare_codes = [c[2:] if c.startswith(("sh", "sz")) else c for c in code_list]
        search_codes = list(dict.fromkeys(bare_codes + code_list))  # dedup
        auction_placeholders = ",".join("?" * len(search_codes))

        today_rows = db.execute(
            f"SELECT code, auction_vol, auction_price, auction_ratio FROM auction WHERE date=? AND code IN ({auction_placeholders})",
            [today_date] + search_codes,
        ).fetchall()
        today_map = {r[0]: {"today_vol": r[1], "auction_price": r[2], "auction_ratio": r[3]} for r in today_rows}

        prev_map = {}
        if prev_date:
            prev_rows = db.execute(
                f"SELECT code, auction_vol FROM auction WHERE date=? AND code IN ({auction_placeholders})",
                [prev_date] + search_codes,
            ).fetchall()
            prev_map = {r[0]: r[1] for r in prev_rows}

        # Yesterday trading volume from daily_kline
        prev_vol_map = {}
        if prev_date:
            from utils.config import get_date_col
            date_col, is_int = get_date_col()
            prev_date_val = int(prev_date.replace("-", "")) if is_int else prev_date

            kline_placeholders = ",".join("?" * len(code_list))
            kline_rows = db.execute(
                f"SELECT code, volume FROM daily_kline WHERE {date_col}=? AND code IN ({kline_placeholders})",
                [prev_date_val] + code_list,
            ).fetchall()
            prev_vol_map = {r[0]: r[1] for r in kline_rows}

        # Build result - try bare code first, fall back to prefixed
        result = {}
        for i, code in enumerate(code_list):
            bare = bare_codes[i]
            t = today_map.get(bare) or today_map.get(code) or {}
            result[code] = {
                "today_vol": t.get("today_vol", 0),
                "prev_vol": prev_map.get(bare) or prev_map.get(code) or 0,
                "auction_price": t.get("auction_price", 0),
                "auction_ratio": t.get("auction_ratio", 0),
                "prev_volume": prev_vol_map.get(code, 0),
            }

        return {"auction": result}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Trade Journal (交易日志)
# ---------------------------------------------------------------------------

@router.get("/journal")
def get_journal(days: int = 30) -> dict:
    """Get trade journal entries."""
    try:
        from utils.trade_journal import TradeJournal
        tj = TradeJournal()
        trades = tj.get_recent_trades(days)
        stats = tj.stats(days)
        closed = tj.get_closed_trades()
        return {"trades": trades, "closed": closed, "stats": stats}
    except Exception as e:
        return {"trades": [], "closed": [], "stats": {}, "error": str(e)}


@router.post("/journal/log")
def log_trade(data: dict) -> dict:
    """Log a new trade entry."""
    try:
        from utils.trade_journal import TradeJournal
        tj = TradeJournal()
        tj.log_trade(
            code=data.get("code", ""),
            name=data.get("name", ""),
            action=data.get("action", "buy"),
            price=data.get("price", 0),
            shares=data.get("shares", 0),
            reason=data.get("reason", ""),
            stop=data.get("stop"),
            target=data.get("target"),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/journal/close")
def close_trade(data: dict) -> dict:
    """Close a trade in journal."""
    try:
        from utils.trade_journal import TradeJournal
        tj = TradeJournal()
        tj.close_trade(
            code=data.get("code", ""),
            exit_price=data.get("exit_price", 0),
            exit_reason=data.get("exit_reason", ""),
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/journal/weekly")
def weekly_report() -> dict:
    """Get weekly trade report."""
    try:
        from utils.trade_journal import TradeJournal
        tj = TradeJournal()
        report = tj.weekly_report()
        return {"report": report}
    except Exception as e:
        return {"report": "", "error": str(e)}


# ---------------------------------------------------------------------------
# AI Analysis (AI分析)
# ---------------------------------------------------------------------------

@router.post("/ai/analyze")
def ai_analyze(data: dict) -> dict:
    """Analyze stocks using LLM."""
    codes = data.get("codes", [])
    if not codes:
        return {"error": "No codes provided"}

    try:
        from utils.llm_analyzer import analyze_stocks

        # Gather stock data
        stocks = []
        db = _get_db()
        if db:
            try:
                cur = db.cursor()
                for code in codes:
                    cur.execute(f"SELECT name FROM {_stock_table()} WHERE code=?", (code,))
                    row = cur.fetchone()
                    name = row[0] if row else code
                    stocks.append({"code": code, "name": name})
            finally:
                db.close()

        report = analyze_stocks(stocks)
        return {"report": report}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Backtest Evaluation (回测评估)
# ---------------------------------------------------------------------------

@router.post("/backtest/eval")
def backtest_eval(data: dict) -> dict:
    """Evaluate stock picks by computing forward returns."""
    picks = data.get("picks", [])
    eval_days = data.get("eval_days", 5)
    if not picks:
        return {"error": "No picks provided"}

    try:
        from utils.backtest_eval import evaluate_picks
        report = evaluate_picks(picks, eval_days)
        return {"report": report}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# News Search (新闻查询)
# ---------------------------------------------------------------------------

@router.get("/news")
def search_news(q: str = "", stock_code: str = "") -> dict:
    """Search news by keyword or stock code."""
    try:
        from utils.news_search import get_stock_news

        if stock_code:
            db = _get_db()
            name = ""
            if db:
                try:
                    cur = db.cursor()
                    cur.execute(f"SELECT name FROM {_stock_table()} WHERE code=?", (stock_code,))
                    row = cur.fetchone()
                    name = row[0] if row else ""
                finally:
                    db.close()
            items = get_stock_news(stock_code, name)
            return {"items": items}

        # General search — use iwencai
        from utils.iwencai import IwencaiClient
        client = IwencaiClient()
        results = client.search(q, perpage=10)
        return {"items": results}
    except Exception as e:
        return {"items": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Sector Momentum (板块动量)
# ---------------------------------------------------------------------------

@router.get("/sectors/momentum")
def sector_momentum() -> dict:
    """Get sector momentum via Tencent industry index quotes (no DB dependency)."""
    try:
        sectors = _fetch_sector_momentum(_SECTOR_CODES_SUBSET)
        return {"sectors": sectors}
    except Exception:
        return {"sectors": []}


@router.get("/sectors/stocks")
def sector_stocks(industry: str = "") -> dict:
    """Get stocks in a specific sector."""
    if not industry:
        return {"stocks": []}
    try:
        from utils.sector_utils import get_industry_map
        industry_map = get_industry_map()
        stocks = [{"code": c, "industry": ind} for c, ind in industry_map.items() if ind == industry]
        return {"stocks": stocks[:50]}
    except Exception as e:
        return {"stocks": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Scheduled Runs Proxy (定时任务代理)
# ---------------------------------------------------------------------------

@router.get("/scheduled-runs")
def list_scheduled_runs() -> dict:
    """List scheduled research runs (proxy to main API)."""
    try:
        url = f"{_BASE_URL}/scheduled-runs"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"jobs": []}


@router.post("/scheduled-runs")
def create_scheduled_run(data: dict) -> dict:
    """Create a scheduled research run (proxy to main API)."""
    try:
        url = f"{_BASE_URL}/scheduled-runs"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


@router.delete("/scheduled-runs/{job_id}")
def delete_scheduled_run(job_id: str) -> dict:
    """Delete a scheduled run (proxy to main API)."""
    try:
        url = f"{_BASE_URL}/scheduled-runs/{job_id}"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Review Report (复盘报告)
# ---------------------------------------------------------------------------

@router.get("/review-report")
def get_review_report(date: str = "") -> dict:
    """Return the generated review report markdown content."""
    report_date = date if date else datetime.now().strftime("%Y-%m-%d")
    safe_name = Path(report_date).name
    report_file = _PROJECT_ROOT / "reports" / f"{safe_name}.md"
    if report_file.exists() and report_file.parent == _PROJECT_ROOT / "reports":
        return {"content": report_file.read_text(encoding="utf-8")}
    return {"content": ""}


# ---------------------------------------------------------------------------
# Auction Board (集合竞价看板)
# ---------------------------------------------------------------------------

def _check_auction_time() -> tuple[bool, dict | None]:
    """Check if auction collection is allowed.
    
    Returns (blocked, response). If blocked, response contains the payload to return.
    After 09:30, collection is blocked and existing data is returned if available.
    """
    now = datetime.now()
    after_cutoff = now.hour > 9 or (now.hour == 9 and now.minute >= 30)
    if not after_cutoff:
        return False, None

    db = _get_db()
    if db is None:
        return True, {"ok": False, "error": "no database"}
    try:
        today_str = date.today().isoformat()
        cur = db.cursor()
        existing = cur.execute("SELECT COUNT(*) FROM auction WHERE date=?", (today_str,)).fetchone()[0]
        if existing > 0:
            return True, {"ok": True, "count": existing, "status": "exists"}
        return True, {"ok": False, "error": "今日尚无竞价数据（09:30后无法采集）", "status": "no_data"}
    finally:
        db.close()


@router.post("/auction/collect")
def collect_auction_data():
    """Collect auction data from Tencent for all stocks and store in DB.
    
    Only collects before 09:30. After 09:30, returns existing data if available.
    """
    blocked, resp = _check_auction_time()
    if blocked:
        return resp

    db = _get_db()
    if db is None:
        return {"ok": False, "error": "no database"}
    today_str = date.today().isoformat()
    try:
        from utils.tencent_quotes import fetch_raw, _parse_basic, add_prefix
        row = _latest_trade_date(db)
        if not row:
            return {"ok": False, "error": "no kline data"}
        latest_date = row

        cur.execute(f"SELECT code FROM {_stock_table()} WHERE code LIKE 'sh%' OR code LIKE 'sz%' OR code LIKE 'bj%'")
        all_codes = [row[0] for row in cur.fetchall()]
        prefixed = [add_prefix(c) for c in all_codes]

        raw = fetch_raw(prefixed)
        collected = 0
        for raw_code, fields in raw.items():
            if len(fields) < 48:
                continue
            basic = _parse_basic(fields)
            code = raw_code
            vol = int(basic["volume"])
            amount = basic["amount"]
            price = basic["price"]
            open_px = basic["open"]
            name = fields[1]
            prev_close = float(fields[4]) if fields[4] else 0
            ratio = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
            try:
                bare_code = code[2:] if code.startswith(("sh", "sz", "bj")) else code
                cur.execute(
                    "INSERT OR REPLACE INTO auction (date, code, name, auction_vol, auction_amount, total_vol, total_amount, auction_ratio, auction_price, open_price, collect_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (today_str, bare_code, name, vol, amount, vol, amount, ratio, price, open_px, datetime.now().strftime("%H:%M:%S"))
                )
                collected += 1
            except Exception:
                _log.warning("auction insert failed for %s", code, exc_info=True)
        db.commit()
        return {"ok": True, "count": collected, "status": "collected"}
    except Exception as e:
        _log.warning("auction collect failed", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


@router.get("/auction/dates")
def get_auction_dates():
    """Return list of dates with auction data."""
    db = _get_db()
    if db is None:
        return {"dates": []}
    try:
        cur = db.cursor()
        cur.execute("SELECT date, COUNT(*), COALESCE(SUM(auction_vol), 0), COALESCE(AVG(auction_ratio), 0) FROM auction GROUP BY date ORDER BY date DESC")
        dates = [{"date": r[0], "count": r[1], "total_vol": r[2], "avg_ratio": round(r[3], 2)} for r in cur.fetchall()]
        return {"dates": dates}
    except Exception as e:
        _log.warning("auction dates failed", exc_info=True)
        return {"dates": []}
    finally:
        db.close()


@router.get("/auction/latest")
def get_auction_latest(date: str = "", limit: int = 100):
    """Return auction stocks for a given date."""
    if not date:
        return {"stocks": [], "leaders": [], "stats": None}
    db = _get_db()
    if db is None:
        return {"stocks": [], "leaders": [], "stats": None}
    try:
        cur = db.cursor()
        cur.execute("SELECT code, name, auction_vol, auction_amount, auction_ratio, auction_price, open_price, total_vol, total_amount FROM auction WHERE date=? ORDER BY auction_vol DESC LIMIT ?", (date, limit))
        rows = cur.fetchall()
        stocks = []
        for r in rows:
            stocks.append({
                "code": r[0], "name": r[1], "auction_vol": r[2], "auction_amount": r[3],
                "auction_ratio": r[4], "auction_price": r[5], "open_price": r[6],
                "total_vol": r[7], "total_amount": r[8],
            })
        count = len(stocks)
        total_vol = sum(s["auction_vol"] for s in stocks)
        total_amount = sum(s["auction_amount"] for s in stocks)
        avg_ratio = round(sum(s["auction_ratio"] for s in stocks) / count, 2) if count else 0
        leaders = sorted(stocks, key=lambda s: s["auction_vol"], reverse=True)[:5]
        return {
            "stocks": stocks,
            "leaders": leaders,
            "stats": {"count": count, "total_vol": total_vol, "total_amount": total_amount, "avg_ratio": avg_ratio},
        }
    except Exception as e:
        _log.warning("auction latest failed", exc_info=True)
        return {"stocks": [], "leaders": [], "stats": None}
    finally:
        db.close()


@router.get("/auction/compare")
def get_auction_compare(date1: str = "", date2: str = "", top: int = 30):
    """Compare auction data between two dates."""
    if not date1 or not date2:
        return {"gainers": [], "losers": [], "increase": 0, "decrease": 0, "total": 0}
    db = _get_db()
    if db is None:
        return {"gainers": [], "losers": [], "increase": 0, "decrease": 0, "total": 0}
    try:
        cur = db.cursor()
        cur.execute("SELECT code, name, auction_vol, auction_price, auction_ratio FROM auction WHERE date=?", (date1,))
        d1_map = {r[0]: {"name": r[1], "vol": r[2], "price": r[3], "ratio": r[4]} for r in cur.fetchall()}
        cur.execute("SELECT code, name, auction_vol, auction_price, auction_ratio FROM auction WHERE date=?", (date2,))
        d2_map = {r[0]: {"name": r[1], "vol": r[2], "price": r[3], "ratio": r[4]} for r in cur.fetchall()}

        all_codes = set(d1_map) | set(d2_map)
        diff = []
        for code in all_codes:
            v1 = d1_map.get(code, {}).get("vol", 0) or 0
            v2 = d2_map.get(code, {}).get("vol", 0) or 0
            name = d1_map.get(code, d2_map.get(code, {})).get("name", "")
            chg = v2 - v1
            pct = round((v2 - v1) / v1 * 100, 2) if v1 else 0
            diff.append({
                "code": code, "name": name,
                "vol_today": v2, "vol_prev": v1,
                "vol_chg": chg, "vol_pct": pct,
                "price_today": d2_map.get(code, {}).get("price", 0),
                "ratio_today": d2_map.get(code, {}).get("ratio", 0),
            })

        diff.sort(key=lambda x: x["vol_chg"], reverse=True)
        gainers = [d for d in diff if d["vol_chg"] > 0][:top]
        losers = [d for d in diff if d["vol_chg"] < 0][:top]
        increase = sum(1 for d in diff if d["vol_chg"] > 0)
        decrease = sum(1 for d in diff if d["vol_chg"] < 0)
        return {
            "date1": date1, "date2": date2,
            "gainers": gainers, "losers": losers,
            "increase": increase, "decrease": decrease,
            "total": len(diff),
        }
    except Exception as e:
        _log.warning("auction compare failed", exc_info=True)
        return {"gainers": [], "losers": [], "increase": 0, "decrease": 0, "total": 0}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Market Ladder (连板梯队)
# ---------------------------------------------------------------------------

@router.get("/market/ladder")
def get_market_ladder():
    """Get real-time limit-up ladder analysis."""
    db = _get_db()
    if db is None:
        return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": ""}
    try:
        from utils.tencent_quotes import fetch_raw, _parse_basic, add_prefix

        latest_date = _latest_trade_date(db)
        if not latest_date:
            return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": ""}

        cur = db.cursor()
        industry_map = _load_industry_map()

        def _limit_threshold(raw_code):
            if raw_code.startswith("sh68") or raw_code.startswith("sz30"):
                return 1.195
            if raw_code.startswith("sh8") or raw_code.startswith("bj"):
                return 1.295
            return 1.095

            # Find stocks that closed near limit-up
        cur.execute(f"""
            SELECT a.code, a.close, a.open, b.close as prev_close
            FROM daily_kline a
            JOIN daily_kline b ON a.code = b.code AND b.date = (
                SELECT MAX(c.date) FROM daily_kline c WHERE c.code = a.code AND c.date < a.date
            )
            WHERE a.date = ? AND (
                (a.code LIKE 'sh6%' OR a.code LIKE 'sz0%' OR a.code LIKE 'sz3%') AND a.close >= b.close * 1.09
            )
            ORDER BY a.close / b.close DESC
        """, (latest_date,))
        candidates = cur.fetchall()
        if not candidates:
            return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": ""}

        codes = [r[0] for r in candidates]
        raw = fetch_raw(codes)
        stock_map = {r[0]: r for r in candidates}

        # Batch fetch kline data for board counting (1 query instead of N)
        placeholders = ",".join("?" for _ in codes)
        cur.execute(f"SELECT code, date, close FROM daily_kline WHERE code IN ({placeholders}) ORDER BY code, date DESC", codes)
        kline_rows = cur.fetchall()
        kline_map: dict[str, list[tuple[str, float]]] = {}
        for code, dt, close in kline_rows:
            kline_map.setdefault(code, []).append((dt, close))

        def count_boards(raw_code):
            threshold = _limit_threshold(raw_code)
            rows = kline_map.get(raw_code, [])
            boards = 0
            for i in range(1, len(rows)):
                prev_close = rows[i][1]
                if prev_close > 0 and rows[i-1][1] >= prev_close * threshold:
                    boards += 1
                else:
                    break
            return boards + 1

        ladder = []
        for raw_code, fields in raw.items():
            if len(fields) < 48:
                continue
            basic = _parse_basic(fields)
            code = raw_code
            cand = stock_map.get(code)
            if not cand:
                continue
            chg = basic["change_pct"]
            board = count_boards(code)
            name = fields[1]
            concepts = [industry_map.get(code, "")] if industry_map.get(code, "") else []
            ladder.append({
                "code": code, "name": name,
                "price": basic["price"], "chg_pct": chg,
                "board": board, "amount": basic["amount"],
                "volume": int(basic["volume"]), "concepts": concepts,
            })

        ladder.sort(key=lambda s: (-s["board"], -s["chg_pct"]))
        by_board = {}
        for s in ladder:
            b = str(s["board"])
            by_board.setdefault(b, []).append(s)
        by_concept = {}
        for s in ladder:
            for c in s["concepts"]:
                by_concept.setdefault(c, []).append(s)

        total = len(ladder)
        first = sum(1 for s in ladder if s["board"] == 1)
        cont = total - first
        max_b = max(s["board"] for s in ladder) if ladder else 0
        dist = {}
        for s in ladder:
            b = str(s["board"])
            dist[b] = dist.get(b, 0) + 1

        return {
            "ladder": ladder,
            "by_board": by_board,
            "by_concept": by_concept,
            "stats": {
                "total_limit_up": total,
                "first_board": first,
                "continue_up": cont,
                "max_board": max_b,
                "board_distribution": dist,
            },
            "summary": f"共 {total} 只涨停，首板 {first} 只，连板 {cont} 只，最高 {max_b} 板",
        }
    except Exception as e:
        _log.warning("market ladder failed", exc_info=True)
        return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": str(e)}
    finally:
        if db:
            db.close()


# ---------------------------------------------------------------------------
# Volume Ranking (成交额排行)
# ---------------------------------------------------------------------------

@router.get("/market/volume-rank")
def get_volume_rank(limit: int = 50):
    """Get volume ranking from latest kline + real-time Tencent data."""
    db = _get_db()
    if db is None:
        return {"stocks": [], "by_industry": {}, "industry_ranking": [], "stats": None}
    try:
        from utils.tencent_quotes import fetch_raw, _parse_basic, add_prefix

        latest_date = _latest_trade_date(db)
        if not latest_date:
            return {"stocks": [], "by_industry": {}, "industry_ranking": [], "stats": None}

        cur = db.cursor()
        cur.execute(f"""
            SELECT a.code, a.close, a.amount, a.volume, a.high, a.low, a.open
            FROM daily_kline a
            WHERE a.date = ?
            ORDER BY a.amount DESC
            LIMIT ?
        """, (latest_date, limit))
        top_stocks = cur.fetchall()

        codes = [add_prefix(r[0]) for r in top_stocks]
        raw = fetch_raw(codes)
        code_map = {add_prefix(r[0]): r for r in top_stocks}

        industry_map = _load_industry_map()

        stocks = []
        for raw_code, fields in raw.items():
            if len(fields) < 48:
                continue
            basic = _parse_basic(fields)
            code = raw_code
            stored = code_map.get(code)
            if not stored:
                continue
            name = fields[1]
            ind = industry_map.get(code, "")
            stocks.append({
                "code": code, "name": name,
                "price": basic["price"], "chg_pct": basic["change_pct"],
                "amount": basic["amount"], "volume": int(basic["volume"]),
                "industry": ind,
                "high": basic["high"], "low": basic["low"], "open": basic["open"],
            })

        stocks.sort(key=lambda s: -s["amount"])
        by_industry = {}
        for s in stocks:
            ind = s["industry"] or "其他"
            by_industry.setdefault(ind, []).append(s)

        industry_ranking = [
            {"industry": ind, "total_amount": sum(s["amount"] for s in ss), "pct": 0}
            for ind, ss in by_industry.items()
        ]
        total_amt = sum(r["total_amount"] for r in industry_ranking)
        for r in industry_ranking:
            r["pct"] = round(r["total_amount"] / total_amt * 100, 1) if total_amt else 0
        industry_ranking.sort(key=lambda r: -r["total_amount"])

        top = stocks[:5]
        stats = {
            "total_stocks": len(stocks),
            "total_amount": total_amt,
            "top_name": top[0]["name"] if top else "",
            "top_amount": top[0]["amount"] if top else 0,
        }

        return {"stocks": stocks, "by_industry": by_industry, "industry_ranking": industry_ranking, "stats": stats}
    except Exception as e:
        _log.warning("volume rank failed", exc_info=True)
        return {"stocks": [], "by_industry": {}, "industry_ranking": [], "stats": None}
    finally:
        if db:
            db.close()


# ---------------------------------------------------------------------------
# Stock Analysis (个股深度分析)
# ---------------------------------------------------------------------------

@router.get("/stock-analysis/{code}")
def get_stock_analysis(code: str):
    """Return Fibonacci cycle analysis + indicators for a stock."""
    db = _get_db()
    if db is None:
        return {"data": {"error": "no database"}}
    try:
        from utils.tencent_quotes import add_prefix
        from utils.fibonacci_formula import find_latest_cycle, fibonacci_price, fibonacci_exit
        from utils.indicators import calc_rsi
        from utils.runaway_price import calc_runaway_price

        # Ensure code has prefix for DB queries (DB stores sz000001 / sh600519)
        prefixed = add_prefix(code)
        db_code = prefixed

        # Get kline data
        cur = db.cursor()
        cur.execute("SELECT date, open, high, low, close, volume FROM daily_kline WHERE code=? ORDER BY date DESC LIMIT 120", (db_code,))
        rows = cur.fetchall()
        if not rows:
            return {"data": {"error": "no kline data for " + code}}

        # Reverse to get chronological order
        rows = rows[::-1]

        dates = [r[0] for r in rows]
        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        volumes = [r[5] for r in rows]
        n = len(closes)

        # Current price from Tencent
        try:
            from utils.tencent_quotes import fetch_detail
            rt = fetch_detail([prefixed])
            q = rt.get(prefixed, {})
            current_price = q.get("price", closes[-1])
        except Exception:
            current_price = closes[-1]

        # Indicators
        indicators = {
            "ma5": _ma(closes, 5), "ma10": _ma(closes, 10),
            "ma20": _ma(closes, 20), "ma60": _ma(closes, 60),
            "rsi14": round(calc_rsi(closes, 14), 2) if len(closes) >= 14 else 0,
            "avg_vol_5": _ma(volumes, 5), "avg_vol_20": _ma(volumes, 20),
        }

        # Find local highs/lows for cycle detection
        high_arr = highs[:n]
        low_arr = lows[:n]
        date_arr = dates[:n]
        precomputed_highs = []
        precomputed_lows = []

        lookback = 5
        for i in range(1, n - 1):
            start = max(0, i - lookback)
            end = min(n, i + lookback + 1)
            if all(high_arr[i] >= h for h in high_arr[start:end]):
                precomputed_highs.append((i, high_arr[i], str(date_arr[i])))
            if all(low_arr[i] <= l for l in low_arr[start:end]):
                precomputed_lows.append((i, low_arr[i], str(date_arr[i])))

        # Find cycles — only scan at local high points (reduces calls from n to ~hundreds)
        all_cycles = []
        valid_cycles = []
        seen = set()
        for h_idx, H, H_date in precomputed_highs:
            if h_idx < 60 or h_idx in seen:
                continue
            seen.add(h_idx)
            cycle = find_latest_cycle(
                high_arr, low_arr, date_arr, h_idx,
                swing_lookback=90, min_swing=0.08, min_days=3,
                precomputed_highs=precomputed_highs, precomputed_lows=precomputed_lows,
            )
            if cycle:
                swing = round((cycle["H"] - cycle["L"]) / cycle["L"] * 100, 2)
                deviation = round((current_price - cycle["E"]) / cycle["E"] * 100, 2) if cycle["E"] else 0
                normalized = {
                    "h_date": cycle["H_date"], "h_price": cycle["H"],
                    "l_date": cycle["L_date"], "l_price": cycle["L"],
                    "E": cycle["E"], "swing_pct": swing,
                    "days": cycle["cycle_days"],
                    "deviation": deviation,
                    "qualifies": abs(deviation) <= 3,
                }
                all_cycles.append(normalized)
                if normalized["qualifies"]:
                    valid_cycles.append(normalized)

        # Best cycle (latest window)
        best = find_latest_cycle(
            high_arr, low_arr, date_arr, n - 1,
            swing_lookback=90, min_swing=0.08, min_days=3,
            precomputed_highs=precomputed_highs, precomputed_lows=precomputed_lows,
        )

        # Runaway price
        runaway_info = calc_runaway_price(db_code, str(dates[-1])) or {}

        # name
        name = ""
        cur.execute("SELECT name FROM {} WHERE code=?".format(_stock_table()), (db_code,))
        r = cur.fetchone()
        name = r[0] if r else ""

        # Vol ratio
        vol_ratio = 0
        if len(volumes) >= 2:
            vol_ratio = round(volumes[-1] / max(sum(volumes[-21:-1]) / 20, 1), 2) if len(volumes) >= 21 else 0

        # Kline bars for chart
        kline_bars = []
        for i in range(max(0, n - 120), n):
            kline_bars.append({
                "date": str(dates[i]),
                "open": opens[i], "high": highs[i],
                "low": lows[i], "close": closes[i],
                "volume": volumes[i],
            })

        return {
            "data": {
                "code": prefixed, "name": name,
                "current_price": current_price,
                "E": best["E"] if best else 0,
                "X": fibonacci_exit(best["H"], best["L"]) if best else 0,
                "runaway": runaway_info.get("runaway_price", 0),
                "exit_price": 0,
                "window_high": best["H"] if best else 0,
                "window_low": best["L"] if best else 0,
                "window_high_date": best.get("H_date", ""),
                "window_low_date": best.get("L_date", ""),
                "indicators": indicators,
                "cycles": all_cycles[-10:] if all_cycles else [],
                "valid_cycles": valid_cycles[-5:] if valid_cycles else [],
                "vol_ratio": vol_ratio,
                "kline": kline_bars,
            }
        }
    except Exception as e:
        _log.warning("stock analysis failed for %s", code, exc_info=True)
        return {"data": {"error": str(e)}}
    finally:
        if db:
            db.close()


# ---------------------------------------------------------------------------
# Shadow Account (影子账户)
# ---------------------------------------------------------------------------

@router.post("/shadow/analyze")
def shadow_analyze():
    """Run full shadow account analysis: convert paper history → extract rules → render report."""
    import subprocess
    import sys as _sys

    # Step 1: Convert paper trading history to CSV
    convert_script = str(_PROJECT_ROOT / "utils" / "paper_to_shadow.py")
    csv_path = str(_PAPER_DIR / "shadow_account_input.csv")
    try:
        result = subprocess.run(
            [_sys.executable, convert_script],
            capture_output=True, text=True, timeout=30,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            return {"ok": False, "detail": f"转换失败: {result.stderr[:500]}"}
    except Exception as e:
        return {"ok": False, "detail": f"转换异常: {e}"}

    # Step 2: Extract shadow profile + render report via Vibe-Trading agent
    agent_dir = str(Path(__file__).resolve().parent.parent.parent)
    analyze_script = f"""
import sys, json
sys.path.insert(0, r"{agent_dir}")
sys.stdout.reconfigure(encoding='utf-8')

from src.shadow_account import extract_shadow_profile, save_profile, load_profile, run_shadow_backtest, render_shadow_report
from src.shadow_account.backtester import load_cached_result
from pathlib import Path

csv_path = r"{csv_path}"
profile = extract_shadow_profile(csv_path, min_support=3, max_rules=5)
save_profile(profile)

result = load_cached_result(profile.shadow_id)
if result is None:
    try:
        result = run_shadow_backtest(
            profile,
            window_start='2026-01-01',
            window_end='2026-12-31',
            journal_path=csv_path,
        )
    except Exception:
        from src.shadow_account.models import AttributionBreakdown, ShadowBacktestResult
        result = ShadowBacktestResult(
            shadow_id=profile.shadow_id,
            per_market=dict(), combined=dict(), equity_curves=dict(),
            attribution=AttributionBreakdown(
                missed_signals_pnl=0.0, noise_trades_pnl=0.0, early_exit_pnl=0.0,
                late_exit_pnl=0.0, overtrading_pnl=0.0, counterfactual_trades=(),
            ),
            shadow_total_pnl=0.0, real_total_pnl=0.0, delta_pnl=0.0,
        )

report = render_shadow_report(profile, result, today_signals=[])

# Output JSON summary
rules = []
for r in profile.rules:
    rules.append({{
        'rule_id': r.rule_id,
        'human_text': r.human_text,
        'support_count': r.support_count,
        'coverage_rate': r.coverage_rate,
        'holding_days_range': list(r.holding_days_range),
    }})

summary = {{
    'shadow_id': profile.shadow_id,
    'profitable_roundtrips': profile.profitable_roundtrips,
    'total_roundtrips': profile.total_roundtrips,
    'source_market': profile.source_market,
    'typical_holding_days': list(profile.typical_holding_days),
    'rules': rules,
    'shadow_pnl': result.shadow_total_pnl,
    'real_pnl': result.real_total_pnl,
    'delta_pnl': result.delta_pnl,
    'html_path': report['html_path'],
}}
print(json.dumps(summary, ensure_ascii=False))
"""
    try:
        result = subprocess.run(
            [_sys.executable, "-c", analyze_script],
            capture_output=True, text=True, timeout=120,
            cwd=agent_dir,
        )
        if result.returncode != 0:
            return {"ok": False, "detail": f"分析失败: {result.stderr[:500]}"}
        summary = json.loads(result.stdout.strip().split("\n")[-1])
        return {"ok": True, **summary}
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "分析超时（>120s）"}
    except Exception as e:
        return {"ok": False, "detail": f"分析异常: {e}"}


@router.get("/shadow/report/{shadow_id}")
def shadow_report(shadow_id: str):
    """Return the shadow account HTML report content."""
    import re
    if not re.match(r"^shadow_[0-9a-f]{8}$", shadow_id):
        return {"ok": False, "detail": "invalid shadow_id"}
    report_path = Path.home() / ".vibe-trading" / "shadow_reports" / f"{shadow_id}.html"
    if not report_path.exists():
        return {"ok": False, "detail": "报告不存在，请先运行分析"}
    html = report_path.read_text(encoding="utf-8")
    return {"ok": True, "html": html}


@router.get("/shadow/list")
def shadow_list():
    """List all existing shadow account reports."""
    reports_dir = Path.home() / ".vibe-trading" / "shadow_reports"
    if not reports_dir.exists():
        return {"ok": True, "reports": []}
    reports = []
    for f in sorted(reports_dir.glob("shadow_*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        shadow_id = f.stem
        reports.append({
            "shadow_id": shadow_id,
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"ok": True, "reports": reports}


def register_trading_tools_routes(app, require_auth=None):
    """Register trading tools routes on the FastAPI app."""
    dependencies = []
    if require_auth is not None:
        dependencies = [Depends(require_auth)]

    # Override router dependencies if auth is required
    if dependencies:
        for route in router.routes:
            if hasattr(route, "dependencies"):
                route.dependencies = dependencies

    app.include_router(router)

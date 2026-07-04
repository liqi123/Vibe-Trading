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
    # Try config DB path first (project convention: from utils.config import DB_PATH)
    try:
        from utils.config import DB_PATH
        if Path(str(DB_PATH)).exists():
            return sqlite3.connect(str(DB_PATH))
    except Exception:
        pass
    # Fallback to project root path
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
            "SELECT code, name FROM stock_names "
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
                cur.execute("SELECT code, name FROM stock_names WHERE name LIKE ? LIMIT 1", (f"%{raw}%",))
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
            cur.execute("SELECT name FROM stock_names WHERE code = ?", (code,))
            row = cur.fetchone()
            if row:
                name = row[0]
        finally:
            db.close()

    # Fallback: get from Tencent API
    if not name:
        try:
            import urllib.request
            url = f"https://qt.gtimg.cn/q={code}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("gbk", errors="replace")
            fields = text.split('"')[1].split("~") if '"' in text else []
            if len(fields) > 4:
                name = fields[1]
                prev_close = float(fields[4]) if fields[4] else 0
        except Exception:
            pass

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
    """Collect auction data for all expectation stocks via Tencent API."""
    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    if not positions:
        return {"stocks": []}

    codes = [p["code"] for p in positions if p.get("code")]
    if not codes:
        return {"stocks": []}

    # Batch fetch from Tencent
    results = []
    import urllib.request
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        url = f"https://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("gbk", errors="replace")
            for line in text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                raw = line.split('"')[1] if '"' in line else ""
                if not raw:
                    continue
                fields = raw.split("~")
                if len(fields) < 48:
                    continue
                code_field = fields[2]
                if code_field.startswith("6") or code_field.startswith("000"):
                    code = "sh" + code_field
                else:
                    code = "sz" + code_field

                name = fields[1]
                price = float(fields[3]) if fields[3] else 0
                prev_close = float(fields[4]) if fields[4] else 0
                change_pct = float(fields[32]) if fields[32] else 0

                # Auction vol (use volume as proxy)
                today_vol = int(fields[6]) if fields[6] else 0
                prev_vol = int(fields[36]) if fields[36] else 0
                vol_ratio = prev_vol > 0 and today_vol > 0 and today_vol / prev_vol or 0

                results.append({
                    "code": code,
                    "name": name,
                    "auction_price": price,
                    "auction_change_pct": change_pct,
                    "today_vol": today_vol,
                    "prev_vol": prev_vol,
                    "vol_ratio": round(vol_ratio, 2),
                })
        except Exception:
            continue

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
        pass

    # Fallback: query DB directly, handle mixed date formats
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        date_int = int(date.replace("-", ""))
        # Try both string and integer date formats
        row = db.execute(
            "SELECT open, high, low, close FROM daily_kline WHERE code=? AND (trade_date=? OR trade_date=?)",
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
    cost = buy_price * sell_shares
    # Get current price from Tencent
    current_price = pos.get("current_price", buy_price)
    try:
        import urllib.request
        url = f"https://qt.gtimg.cn/q={code}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", errors="replace")
        fields = text.split('"')[1].split("~") if '"' in text else []
        if len(fields) > 3 and fields[3]:
            current_price = float(fields[3])
    except Exception:
        pass

    pnl = (current_price - buy_price) * sell_shares
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0

    from datetime import date
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
        try:
            cur.execute("SELECT date FROM daily_kline LIMIT 1")
            date_col = "date"
        except Exception:
            date_col = "trade_date"

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


@router.get("/market/realtime")
def get_market_realtime() -> dict:
    """Real-time market advance/decline stats via Tencent API (single batch request)."""
    import urllib.request as _req
    import logging
    _log = logging.getLogger("trading_tools")

    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        cur.execute("SELECT code FROM stock_names")
        codes_raw = [r[0] for r in cur.fetchall()]
    finally:
        db.close()

    if not codes_raw:
        return {"up": 0, "down": 0, "flat": 0, "limit_up": 0, "limit_down": 0, "total": 0}

    # Convert to Tencent format
    def to_tencent(c: str) -> str:
        c = c.strip().lower()
        if c.startswith(("sh", "sz")):
            return c
        if c.startswith("6"):
            return "sh" + c
        return "sz" + c

    tencent_codes = [to_tencent(c) for c in codes_raw]

    # Batch request (URL length limit ~8000 chars, ~800 codes per batch)
    up = down = flat = limit_up = limit_down = 0
    batch_size = 800
    try:
        for i in range(0, len(tencent_codes), batch_size):
            batch = tencent_codes[i:i+batch_size]
            url = "https://qt.gtimg.cn/q=" + ",".join(batch)
            req = _req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _req.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("gbk", errors="replace")
            for line in text.strip().split(";"):
                if "=" not in line or "~" not in line:
                    continue
                try:
                    raw = line.split('"')[1]
                    fields = raw.split("~")
                    if len(fields) < 35:
                        continue
                    change_pct = float(fields[32]) if fields[32] else 0
                    price = float(fields[3]) if fields[3] else 0
                    prev_close = float(fields[4]) if fields[4] else 0
                    if change_pct > 0:
                        up += 1
                    elif change_pct < 0:
                        down += 1
                    else:
                        flat += 1
                    if prev_close > 0 and price > 0:
                        actual_pct = (price - prev_close) / prev_close
                        if actual_pct >= 0.098:
                            limit_up += 1
                        elif actual_pct <= -0.098:
                            limit_down += 1
                except (ValueError, IndexError):
                    continue
    except Exception as exc:
        _log.warning("Tencent batch query failed: %s", exc)

    return {
        "up": up, "down": down, "flat": flat,
        "limit_up": limit_up, "limit_down": limit_down,
        "total": up + down + flat,
    }


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

import subprocess

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
            pass
        except Exception:
            pass

    # Fallback: Tencent realtime
    tencent_script = _PROJECT_ROOT / "tdx_utils" / "update_tencent.py"
    if tencent_script.exists():
        try:
            result = subprocess.run(
                ["python", str(tencent_script)],
                capture_output=True, text=True, timeout=300,
                cwd=str(_PROJECT_ROOT),
            )
            stdout = result.stdout or ""
            if result.returncode == 0:
                return {"ok": True, "method": "tencent", "message": stdout.strip().split("\n")[-1]}
        except Exception:
            pass

    return {"ok": False, "method": "none", "message": "No update script found or all methods failed"}


# ---------------------------------------------------------------------------
# Trade History (交易记录)
# ---------------------------------------------------------------------------

@router.post("/run-script")
def run_script(data: dict):
    """Run a trading script in background thread, return task id."""
    import uuid
    import threading
    from datetime import datetime

    script = data.get("script", "")
    scripts = {
        "fibonacci": "strategies/daily_check.py",
        "v5": "strategies/daily_check_v5.py",
        "stops": "-m utils stops",
    }
    if script not in scripts:
        raise HTTPException(status_code=400, detail=f"Unknown script: {script}")

    task_id = str(uuid.uuid4())[:8]
    cmd = scripts[script]
    output_file = _PAPER_DIR / f"script_output_{task_id}.txt"

    output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 执行中...\n", encoding="utf-8")

    if cmd.startswith("-m"):
        args = ["python"] + cmd.split()
    else:
        args = ["python", cmd]

    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    def _run():
        try:
            proc = subprocess.Popen(
                ["python", "-X", "utf8"] + args[1:],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
                env=env,
            )
            stdout, _ = proc.communicate(timeout=600)
            text = stdout.decode("utf-8", errors="replace") if stdout else ""
            ts = datetime.now().strftime("%H:%M:%S")
            output_file.write_text(f"[{ts}] 执行完成 (exit={proc.returncode})\n\n{text}", encoding="utf-8")
        except subprocess.TimeoutExpired:
            proc.kill()
            output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 超时(10分钟)\n", encoding="utf-8")
        except Exception as e:
            output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {e}\n", encoding="utf-8")

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/run-script/{task_id}")
def get_script_output(task_id: str):
    """Get script execution output."""
    output_file = _PAPER_DIR / f"script_output_{task_id}.txt"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    content = output_file.read_text(encoding="utf-8")
    return {"output": content}


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

    # Use config DB path (not _DB_PATH which may be wrong)
    try:
        from utils.config import DB_PATH as _REAL_DB
    except Exception:
        _REAL_DB = _DB_PATH

    if not Path(_REAL_DB).exists():
        return {"auction": {}}

    db = sqlite3.connect(str(_REAL_DB))
    try:
        dates = [r[0] for r in db.execute(
            "SELECT DISTINCT date FROM auction ORDER BY date DESC LIMIT 2"
        ).fetchall()]
        if not dates:
            return {"auction": {}}

        today_date = dates[0]
        prev_date = dates[1] if len(dates) > 1 else None

        # Auction table stores codes without sh/sz prefix
        bare_codes = [c[2:] if c.startswith(("sh", "sz")) else c for c in code_list]
        placeholders = ",".join("?" * len(bare_codes))

        today_rows = db.execute(
            f"SELECT code, auction_vol, auction_price, auction_ratio FROM auction WHERE date=? AND code IN ({placeholders})",
            [today_date] + bare_codes,
        ).fetchall()
        today_map = {r[0]: {"today_vol": r[1], "auction_price": r[2], "auction_ratio": r[3]} for r in today_rows}

        prev_map = {}
        if prev_date:
            prev_rows = db.execute(
                f"SELECT code, auction_vol FROM auction WHERE date=? AND code IN ({placeholders})",
                [prev_date] + bare_codes,
            ).fetchall()
            prev_map = {r[0]: r[1] for r in prev_rows}

        # Yesterday trading volume from daily_kline
        prev_vol_map = {}
        if prev_date:
            # Detect date column
            try:
                db.execute("SELECT date FROM daily_kline LIMIT 1")
                date_col = "date"
            except Exception:
                date_col = "trade_date"

            kline_rows = db.execute(
                f"SELECT code, volume FROM daily_kline WHERE {date_col}=? AND code IN ({placeholders})",
                [prev_date] + code_list,
            ).fetchall()
            if not kline_rows and date_col == "date":
                prev_date_int = int(prev_date.replace("-", ""))
                kline_rows = db.execute(
                    f"SELECT code, volume FROM daily_kline WHERE trade_date=? AND code IN ({placeholders})",
                    [prev_date_int] + code_list,
                ).fetchall()
            prev_vol_map = {r[0]: r[1] for r in kline_rows}

        # Build result - map bare codes back to full codes
        result = {}
        for i, code in enumerate(code_list):
            bare = bare_codes[i]
            t = today_map.get(bare, {})
            result[code] = {
                "today_vol": t.get("today_vol", 0),
                "prev_vol": prev_map.get(bare, 0),
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
        sys.path.insert(0, str(_UTILS_DIR))
        from trade_journal import TradeJournal
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
        sys.path.insert(0, str(_UTILS_DIR))
        from trade_journal import TradeJournal
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
        sys.path.insert(0, str(_UTILS_DIR))
        from trade_journal import TradeJournal
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
        sys.path.insert(0, str(_UTILS_DIR))
        from trade_journal import TradeJournal
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
        sys.path.insert(0, str(_UTILS_DIR))
        from llm_analyzer import analyze_stocks

        # Gather stock data
        stocks = []
        db = _get_db()
        if db:
            try:
                cur = db.cursor()
                for code in codes:
                    cur.execute("SELECT name FROM stock_names WHERE code=?", (code,))
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
        sys.path.insert(0, str(_UTILS_DIR))
        from backtest_eval import evaluate_picks
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
        sys.path.insert(0, str(_UTILS_DIR))
        from news_search import get_stock_news

        if stock_code:
            db = _get_db()
            name = ""
            if db:
                try:
                    cur = db.cursor()
                    cur.execute("SELECT name FROM stock_names WHERE code=?", (stock_code,))
                    row = cur.fetchone()
                    name = row[0] if row else ""
                finally:
                    db.close()
            items = get_stock_news(stock_code, name)
            return {"items": items}

        # General search — use iwencai
        from iwencai import IwencaiClient
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
    # Tencent深证行业板块指数 sz3992xx
    SECTOR_CODES = [
        ("sz399231", "农林牧渔"), ("sz399232", "采矿"), ("sz399233", "制造"),
        ("sz399234", "水电燃气"), ("sz399235", "建筑"), ("sz399236", "批发零售"),
        ("sz399237", "交通运输"), ("sz399238", "餐饮住宿"), ("sz399239", "信息技术"),
        ("sz399240", "金融"), ("sz399241", "房地产"), ("sz399242", "商务服务"),
        ("sz399243", "科研服务"), ("sz399244", "公共管理"), ("sz399248", "文化体育"),
    ]
    codes_str = ",".join(c for c, _ in SECTOR_CODES)
    try:
        url = f"https://qt.gtimg.cn/q={codes_str}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", errors="replace")
        sectors = []
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            raw = line.split('"')[1] if '"' in line else ""
            if not raw or "pv_none" in raw:
                continue
            fields = raw.split("~")
            if len(fields) < 33:
                continue
            try:
                change_pct = float(fields[32])
            except (ValueError, IndexError):
                continue
            # Match name from SECTOR_CODES lookup
            tencent_code = "sz" + fields[2]
            name = next((n for c, n in SECTOR_CODES if c == tencent_code), fields[1])
            sectors.append({"name": name, "momentum": round(change_pct / 100, 4)})
        sectors.sort(key=lambda x: x["momentum"], reverse=True)
        return {"sectors": sectors}
    except Exception:
        return {"sectors": []}


@router.get("/sectors/stocks")
def sector_stocks(industry: str = "") -> dict:
    """Get stocks in a specific sector."""
    if not industry:
        return {"stocks": []}
    try:
        sys.path.insert(0, str(_UTILS_DIR))
        from sector_utils import get_industry_map
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
    import urllib.request
    try:
        url = "http://127.0.0.1:8899/scheduled-runs"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"jobs": []}


@router.post("/scheduled-runs")
def create_scheduled_run(data: dict) -> dict:
    """Create a scheduled research run (proxy to main API)."""
    import urllib.request
    try:
        url = "http://127.0.0.1:8899/scheduled-runs"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


@router.delete("/scheduled-runs/{job_id}")
def delete_scheduled_run(job_id: str) -> dict:
    """Delete a scheduled run (proxy to main API)."""
    import urllib.request
    try:
        url = f"http://127.0.0.1:8899/scheduled-runs/{job_id}"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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

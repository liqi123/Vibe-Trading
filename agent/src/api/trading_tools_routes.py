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
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

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
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _atomic_write_json(path: Path, data: dict | list) -> None:
    """原子写入 JSON，防止并发读取到半写状态。"""
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _ok(**kwargs) -> dict:
    """Unified success response envelope."""
    return {"ok": True, **kwargs}


def _err(detail: str = "", **kwargs) -> dict:
    """Unified error response envelope."""
    return {"ok": False, "detail": detail, **kwargs}


_STOCK_TABLE_CACHE: str | None = None

def _stock_table(db: sqlite3.Connection | None = None) -> str:
    """Auto-detect stocks / stock_names table (result cached)."""
    global _STOCK_TABLE_CACHE
    if _STOCK_TABLE_CACHE is not None:
        return _STOCK_TABLE_CACHE
    own_db = db is None
    if own_db:
        db = _get_db()
        if db is None:
            _STOCK_TABLE_CACHE = 'stock_names'
            return _STOCK_TABLE_CACHE
    try:
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        _STOCK_TABLE_CACHE = 'stock_names' if 'stock_names' in tables else 'stocks'
    except Exception:
        _STOCK_TABLE_CACHE = 'stock_names'
    finally:
        if own_db and db is not None:
            db.close()
    return _STOCK_TABLE_CACHE


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
        cols = {r[1] for r in cur.execute("PRAGMA table_info(daily_kline)").fetchall()}
        date_col = "trade_date" if "trade_date" in cols else "date"
        cur.execute(f"SELECT DISTINCT {date_col} FROM daily_kline ORDER BY {date_col} DESC LIMIT 1")
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
def _load_industry_map() -> dict:
    """Load industry mapping, returns {} on failure."""
    try:
        from data.sector_utils import get_industry_map
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
            code = p["code"]
            bare_code = code[2:] if code.startswith(("sh", "sz")) else code

            # 优先从auction表获取prev_close（更及时）
            auction_row = db.execute(
                "SELECT prev_close FROM auction WHERE code=? ORDER BY date DESC LIMIT 1",
                (bare_code,)
            ).fetchone()
            if auction_row and auction_row[0]:
                p["prev_close"] = auction_row[0]
            else:
                # 回退到daily_kline表
                row = db.execute(
                    f"SELECT close FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 1",
                    (code,)
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
            return _ok(message="Already exists")

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
            from data.tencent_quotes import fetch_detail
            q = fetch_detail([code]).get(code, {})
            name = q.get("name", "")
            prev_close = q.get("prev_close", 0)
        except Exception:
            _log.warning("add_expectation: Tencent fallback failed for %s", code, exc_info=True)

    positions.append({
        "code": code,
        "name": name,
        "prev_close": prev_close,
        "status": "关注中",
    })
    state["positions"] = positions

    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


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
    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


@router.post("/expectations/remove")
def remove_expectation(data: dict):
    """Remove a stock from expectations."""
    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    state["positions"] = [p for p in positions if p.get("code") != code]

    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


@router.post("/expectations/collect-auction")
def collect_auction():
    """Collect auction data for all expectation stocks via Tencent API.
    
    Before 09:30: fetch live from Tencent. After 09:30: read from auction table.
    """
    from data.tencent_quotes import fetch_detail, add_prefix

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
                prev_dates = [r[0] for r in cur.execute(
                    "SELECT DISTINCT date FROM auction WHERE date<? ORDER BY date DESC LIMIT 1", (today_str,)
                ).fetchall()]
                prev_date = prev_dates[0] if prev_dates else None
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
                        prev_row = None
                        if prev_date:
                            prev_row = cur.execute(
                                "SELECT auction_vol FROM auction WHERE date=? AND (code=? OR code=?)",
                                (prev_date, code, bare)
                            ).fetchone()
                        results.append({
                            "code": code,
                            "auction_price": auction_price,
                            "auction_change_pct": change_pct,
                            "today_vol": row[0],
                            "prev_vol": prev_row[0] if prev_row else 0,
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

    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


# ---------------------------------------------------------------------------
# Paper Trading (模拟盘)
# ---------------------------------------------------------------------------

@router.get("/portfolio")
def get_portfolio() -> dict:
    """Return V1 paper trading state (Fibonacci strategy) with live prices."""
    path = _PAPER_DIR / "paper_trading_state.json"
    try:
        from trading.paper_trading import load_state
        state = load_state(path)
    except Exception:
        state = _read_json(path)
    # Sort history newest first
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state


@router.get("/portfolio/v5")
def get_portfolio_trend() -> dict:
    """Return V5 paper trading state (trend strategy) with live prices."""
    path = _PAPER_DIR / "paper_trading_state_trend.json"
    try:
        from trading.paper_trading import load_state
        state = load_state(path)
    except Exception:
        state = _read_json(path)
    # Sort history newest first
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state


@router.get("/portfolio/ict")
def get_portfolio_ict() -> dict:
    """Return ICT/SMC paper trading state with live prices."""
    path = _PAPER_DIR / "paper_trading_state_ict.json"
    try:
        from trading.paper_trading import load_state
        state = load_state(path)
    except Exception:
        state = _read_json(path)
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state


@router.get("/trades/ict")
def get_trades_ict() -> dict:
    """Return ICT/SMC trade history."""
    path = _PAPER_DIR / "paper_trading_state_ict.json"
    state = _read_json(path)
    history = state.get("history", [])
    history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)
    return {"history": history}


# ---------------------------------------------------------------------------
# Composite Volume (复合量价策略) Paper Trading
# ---------------------------------------------------------------------------

@router.get("/composite-volume/signal")
def get_cv_signal() -> dict:
    """Run composite volume strategy live and return today's Top 1% picks."""
    today = date.today().strftime("%Y-%m-%d")
    try:
        from data.tencent_quotes import fetch_detail, add_prefix
    except Exception:
        return _err("data.tencent_quotes 不可用")

    try:
        return _get_cv_signal_impl(today)
    except Exception as exc:
        _log.error("get_cv_signal failed: %s", exc, exc_info=True)
        return _err(str(exc))

def _get_cv_signal_impl(today: str) -> dict:
    from data.tencent_quotes import fetch_detail, add_prefix
    db = _get_db()
    if db is None:
        return _err("无法连接数据库")
    st_numeric = {r[0][2:] for r in db.execute(
        "SELECT code FROM stock_names WHERE name LIKE 'ST%' OR name LIKE '*ST%'"
    ).fetchall()}

    lookback = 200
    end = datetime.strptime(today, "%Y-%m-%d")
    start = (end - timedelta(days=lookback)).strftime("%Y%m%d")
    ed = end.strftime("%Y%m%d")

    valid = {r[0] for r in db.execute("SELECT code FROM stock_names").fetchall()}
    raw = pd.read_sql_query(f"""
        SELECT code, market, trade_date, open, high, low, close, amount, volume
        FROM daily_kline
        WHERE trade_date >= {start} AND trade_date <= {ed}
        ORDER BY code, trade_date
    """, db)
    db.close()
    raw = raw[raw["code"].isin(valid)]
    raw["identifier"] = raw["code"].str[2:] + "." + raw["market"].str.upper()
    raw["date"] = pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d")

    panel = {}
    for col in ("open", "high", "low", "close", "volume"):
        piv = raw.pivot_table(index="date", columns="identifier", values=col, aggfunc="first")
        panel[col] = piv.astype(float)

    identifiers = panel["close"].columns
    tenc_map = {}
    for sid in identifiers:
        num, mkt = sid.split(".")
        pre = "sh" if mkt == "SH" else "sz" if mkt == "SZ" else "bj"
        tenc_map[pre + num] = sid

    all_data = fetch_detail(list(tenc_map.keys()))
    today_dt = pd.to_datetime(today)
    rows_o, rows_h, rows_l, rows_c, rows_v = {}, {}, {}, {}, {}
    for tenc, sid in tenc_map.items():
        q = all_data.get(tenc, {})
        p = q.get("price", 0)
        if p > 0:
            rows_o[sid] = q.get("open", 0)
            rows_h[sid] = q.get("high", 0)
            rows_l[sid] = q.get("low", 0)
            rows_c[sid] = p
            rows_v[sid] = q.get("volume", 0)

    for col, rows in zip(
        ("open", "high", "low", "close", "volume"),
        (rows_o, rows_h, rows_l, rows_c, rows_v),
    ):
        new = pd.DataFrame(rows, index=[today_dt])
        new = new.reindex(columns=panel[col].columns, fill_value=0.0)
        panel[col] = pd.concat([panel[col], new])

    c, v, h, l, o = panel["close"], panel["volume"], panel["high"], panel["low"], panel["open"]
    c_r = c.rank(axis=1, pct=True)
    v_r = v.rank(axis=1, pct=True)
    f1 = (c / c.shift(10) - 1) - (v / v.shift(10) - 1)
    f1 = f1.rank(axis=1, pct=True)
    f2 = (-c_r.rolling(5, min_periods=5).corr(v_r)).rank(axis=1, pct=True)
    f3 = (-h.rolling(5, min_periods=5).corr(v_r)).rank(axis=1, pct=True)
    f4 = (-(v / v.rolling(20).mean())).rank(axis=1, pct=True)
    f5 = (-(v.rolling(10, min_periods=10).std() * c.rolling(5, min_periods=5).corr(v))).rank(axis=1, pct=True)
    f6 = ((o / c.shift(1) - 1)).rank(axis=1, pct=True)
    upper_shadow = (h - np.maximum(c, o)) / c
    f7 = (-upper_shadow.rolling(20, min_periods=10).std()).rank(axis=1, pct=True)
    amihud = c.pct_change().abs() / (v * c)
    f9 = amihud.rolling(20, min_periods=10).mean().rank(axis=1, pct=True)
    # f10: APM — 上午比下午强
    morning_ret = o / c.shift(1) - 1
    afternoon_ret = c / o - 1
    apm_raw = morning_ret.rank(axis=1, pct=True) - afternoon_ret.rank(axis=1, pct=True)
    daily_range = (h - l) / c
    vol_weight = 1.0 / (daily_range.rolling(5).mean() + 1e-8)
    orr = abs(o - c.shift(1)) / c.shift(1)
    full_range = (h - l) / c.shift(1)
    range_ratio = orr / (full_range + 1e-8)
    f10 = (apm_raw * vol_weight / vol_weight.mean()).rank(axis=1, pct=True) + range_ratio.rank(axis=1, pct=True)
    f10 = f10.rank(axis=1, pct=True)
    composite = (f1 + f2 + f3 + f4 + f5 + f6 + f7 + f9 + f10) / 9.0

    scores = composite.loc[today_dt].dropna()
    scores = scores[~scores.index.map(lambda x: x.split(".")[0]).isin(st_numeric)]
    scores = scores.sort_values(ascending=False)
    n_select = max(1, int(len(scores) * 0.01))
    selected = scores.head(n_select)

    codes_q = [add_prefix(c.split(".")[0]) for c in selected.index]
    details = fetch_detail(codes_q)

    picks = []
    for i, (code, score) in enumerate(selected.items(), 1):
        base = code.split(".")[0]
        q = details.get("sh" + base) or details.get("sz" + base) or {}
        price = q.get("price", 0)
        prev_c = q.get("prev_close", 0)
        chg = round((price / prev_c - 1) * 100, 2) if prev_c > 0 else 0
        picks.append({
            "rank": i,
            "code": code,
            "name": q.get("name", ""),
            "score": round(score, 4),
            "price": price,
            "prev_close": prev_c,
            "change_pct": chg,
        })

    return _ok(
        picks=picks,
        count=n_select,
        threshold=round(float(scores.iloc[n_select - 1]), 4),
        median=round(float(scores.median()), 4),
        date=today,
    )


@router.get("/composite-volume/portfolio")
def get_cv_portfolio() -> dict:
    """Return composite volume paper trading state with live prices."""
    path = _PAPER_DIR / "composite_volume_state.json"
    state = _read_json(path)
    if state and state.get("positions"):
        try:
            codes = ["sh" + p["code"].split(".")[0] if p["code"].split(".")[0].startswith(("6", "9"))
                     else "sz" + p["code"].split(".")[0] for p in state["positions"]]
            from data.tencent_quotes import get_prices
            prices = get_prices(codes)
            prefixes = {"sh", "sz", "bj"}
            for p in state["positions"]:
                num = p["code"].split(".")[0]
                for pre in prefixes:
                    if pre + num in prices:
                        p["current_price"] = prices[pre + num]
                        break
        except Exception:
            _log.warning("get_cv_portfolio: live prices failed")
    if "history" in state:
        state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)
    return state if state else {
        "name": "复合量价策略", "strategy": "composite_volume",
        "initial_capital": 200000, "cash": 200000, "positions": [], "history": [],
    }


@router.post("/composite-volume/buy")
def buy_cv_stock(data: dict) -> dict:
    """Buy a stock into composite volume portfolio."""
    code = data.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    path = _PAPER_DIR / "composite_volume_state.json"
    state = _read_json(path)
    if not state:
        state = {"name": "复合量价策略", "strategy": "composite_volume",
                 "initial_capital": 200000, "cash": 200000, "positions": [], "history": []}
    if any(p.get("code") == code for p in state.get("positions", [])):
        return _err("已持仓")
    if len(state.get("positions", [])) >= 5:
        return _err("持仓已达上限(5只)")

    from utils.config import INITIAL_CAPITAL, COMMISSION, SLIPPAGE
    layer = state.get("initial_capital", INITIAL_CAPITAL) / 6
    buy_amount = min(layer, state["cash"] - layer)
    if buy_amount <= 0:
        return _err("现金不足")
    price = data.get("price", 0)
    if price <= 0:
        return _err("无效价格")
    shares = int(buy_amount / price / 100) * 100
    if shares <= 0:
        return _err("股数不足(最少100股)")
    buy_price_adj = price * (1 + SLIPPAGE)
    total_cost = shares * buy_price_adj * (1 + COMMISSION)
    name = data.get("name", "")
    score = data.get("score", 0)
    state["cash"] -= total_cost
    state.setdefault("positions", []).append({
        "code": code, "name": name,
        "buy_price": buy_price_adj, "shares": shares, "cost": total_cost,
        "current_price": buy_price_adj, "score": score,
    })
    state.setdefault("history", []).append({
        "date": date.today().strftime("%Y-%m-%d"), "action": "buy",
        "code": code, "name": name,
        "price": buy_price_adj, "shares": shares, "score": score,
    })
    try:
        _atomic_write_json(path, state)
        return _ok(message=f"买入 {name} {code}: {shares}股 @{buy_price_adj:.2f}",
                   shares=shares, price=buy_price_adj, cost=total_cost)
    except Exception as e:
        return _err(f"保存失败: {e}")


@router.post("/composite-volume/sell")
def sell_cv_position(data: dict) -> dict:
    """Sell a position from composite volume portfolio."""
    code = data.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    path = _PAPER_DIR / "composite_volume_state.json"
    state = _read_json(path)
    positions = state.get("positions", [])
    pos = next((p for p in positions if p.get("code", "").lower() == code.lower()), None)
    if not pos:
        raise HTTPException(status_code=404, detail=f"No position for {code}")

    sell_shares = data.get("shares") or pos.get("shares", 0)
    if sell_shares <= 0:
        return _err("无效股数")
    buy_price = pos.get("buy_price", 0)
    current_price = pos.get("current_price", buy_price)
    try:
        from data.tencent_quotes import get_prices
        num = code.split(".")[0]
        pre = "sh" if num[0] in ("6", "9") else "sz"
        prices = get_prices([pre + num])
        if pre + num in prices:
            current_price = prices[pre + num]
    except Exception:
        _log.warning("sell_cv: get_prices failed")

    pnl = (current_price - buy_price) * sell_shares
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    today = date.today().strftime("%Y-%m-%d")

    state.setdefault("history", []).append({
        "date": today, "action": "sell",
        "code": code, "name": pos.get("name", ""),
        "price": current_price, "shares": sell_shares,
        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        "note": data.get("reason", "手动卖出"),
    })

    remaining = pos.get("shares", 0) - sell_shares
    if remaining <= 0:
        state["positions"] = [p for p in positions if p.get("code") != code]
    else:
        for p in positions:
            if p.get("code") == code:
                p["shares"] = remaining
                p["cost"] = buy_price * remaining
                break
    state["cash"] = state.get("cash", 0) + current_price * sell_shares
    _atomic_write_json(path, state)
    return _ok(pnl=round(pnl, 2), price=current_price)


@router.get("/scan-results")
def get_scan_results(strategy: str = "fibonacci", date: str = "") -> dict:
    """Return cached scan results for given strategy and date.
    13:00之前默认取前一天（当日选股尚未生成），之后取当天。"""
    if not date:
        from datetime import date as _date, datetime
        today = _date.today()
        date = today.strftime("%Y-%m-%d")
        if datetime.now().hour < 13:
            from datetime import timedelta
            date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    prefix = "v1" if strategy == "fibonacci" else "trend" if strategy == "trend" else "ict"

    def _load(cache_date: str) -> dict | None:
        p = _PAPER_DIR / f"{prefix}_screening_cache_{cache_date}.json"
        raw = _read_json(p)
        if not raw:
            return None
        if "candidates" not in raw and "results" in raw:
            raw["candidates"] = raw.pop("results")
        raw["date"] = cache_date
        return raw

    result = _load(date)
    if result is not None:
        return result

    # Fallback: find latest cache file for this strategy
    try:
        files = sorted(_PAPER_DIR.glob(f"{prefix}_screening_cache_*.json"), reverse=True)
        for f in files:
            d = f.stem.replace(f"{prefix}_screening_cache_", "")
            result = _load(d)
            if result is not None:
                result["message"] = f"no cache for {date}, using {d}"
                return result
    except Exception:
        pass

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
        from analysis.runaway_price import calc_runaway_price
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

    Expects: {code, portfolio: "v1"|"trend", field, value}
    """
    code = data.get("code", "").strip().lower()
    portfolio = data.get("portfolio", "trend")
    field = data.get("field", "")
    value = data.get("value")

    if not code or not field:
        raise HTTPException(status_code=400, detail="Code and field required")

    state_file = "paper_trading_state.json" if portfolio == "v1" else "paper_trading_state_trend.json" if portfolio == "trend" else "paper_trading_state_ict.json"
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
    _atomic_write_json(path, state)
    return _ok()


@router.post("/portfolio/sell")
def sell_position(data: dict):
    """Sell a position from paper trading.

    Expects: {code, portfolio: "v1"|"trend"|"ict", shares?, reason?}
    """
    code = data.get("code", "").strip().lower()
    portfolio = data.get("portfolio", "trend")
    shares = data.get("shares")  # None means sell all
    reason = data.get("reason", "手动卖出")

    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state_file = "paper_trading_state.json" if portfolio == "v1" else "paper_trading_state_trend.json" if portfolio == "trend" else "paper_trading_state_ict.json"
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
        from data.tencent_quotes import get_prices
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

    _atomic_write_json(path, state)
    return _ok(pnl=round(pnl, 2), price=current_price)


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
            f"WHERE code = ? ORDER BY {date_col} DESC LIMIT 500",
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


@router.get("/stock/{code}/intraday")
def get_stock_intraday(code: str) -> dict:
    """今日1分钟分时图，含 price + volume + prev_close。"""
    raw = code
    for pfx in ("sh", "sz", "bj"):
        if code.startswith(pfx):
            raw = code[len(pfx):]
            break
    try:
        from datetime import datetime, timedelta

        # 前收盘（DB 中 code 带 sz/sh 前缀）
        prev_close = None
        try:
            import sqlite3
            from pathlib import Path
            candidates = [r"G:\tdx_data\tdx_daily.db", r"E:\DataBase\tdx_data.db"]
            db_path = next((c for c in candidates if Path(c).exists()), None)
            if db_path:
                conn = sqlite3.connect(db_path)
                prefixes = []
                if code.startswith(("sh", "sz", "bj")):
                    prefixes = [code[:2]]
                else:
                    prefixes = ["sz", "sh", "bj"]
                for pfx in prefixes:
                    row = conn.execute(
                        "SELECT close FROM daily_kline WHERE code=? ORDER BY trade_date DESC LIMIT 1",
                        (f"{pfx}{raw}",),
                    ).fetchone()
                    if row:
                        prev_close = float(row[0])
                        break
                conn.close()
        except Exception:
            pass

        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        df = client.minute(symbol=raw)
        if df is not None and len(df) > 0:
            now = datetime.now()
            open_dt = datetime(now.year, now.month, now.day, 9, 31)
            result = []
            for i, (_, r) in enumerate(df.iterrows()):
                bar_dt = open_dt + timedelta(minutes=i)
                if bar_dt.hour == 11 and bar_dt.minute >= 31:
                    bar_dt += timedelta(minutes=89)
                t = bar_dt.strftime("%H:%M")
                p = float(r["price"])
                v = int(r.get("volume", 0))
                result.append({"t": t, "p": p, "v": v})
            return {"code": code, "bars": result, "prev_close": prev_close}
    except Exception:
        pass
    return {"code": code, "bars": [], "prev_close": None}


@router.post("/stock/{code}/buy")
def buy_stock(code: str, data: dict):
    """Buy a stock into paper trading portfolio.

    Expects: {strategy: "fibonacci"|"trend"|"ict", name, price, score?, E?, stop?, ...}
    """
    strategy = data.get("strategy", "fibonacci")
    if strategy == "fibonacci":
        state_file = "paper_trading_state.json"
    elif strategy == "ict":
        state_file = "paper_trading_state_ict.json"
    else:
        state_file = "paper_trading_state_trend.json"
    path = _PAPER_DIR / state_file
    state = _read_json(path)
    if not state:
        state = {"initial_capital": 200000, "cash": 200000, "positions": [], "history": []}

    # Check if already held
    if any(p.get("code") == code for p in state.get("positions", [])):
        return _err("已持仓")

    # Check max positions (5)
    if len(state.get("positions", [])) >= 5:
        return _err("持仓已达上限(5只)")

    from utils.config import INITIAL_CAPITAL, COMMISSION, SLIPPAGE

    layer_divisor = 6
    layer = state.get("initial_capital", INITIAL_CAPITAL) / layer_divisor
    buy_amount = min(layer, state["cash"] - layer)
    if buy_amount <= 0:
        return _err("现金不足")

    price = data.get("price", 0)
    if price <= 0:
        return _err("无效价格")

    shares = int(buy_amount / price / 100) * 100
    if shares <= 0:
        return _err("股数不足(最少100股)")

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
    elif strategy == "ict":
        pos = {
            "code": code, "name": name,
            "buy_price": buy_price_adj, "shares": shares, "cost": total_cost,
            "current_price": buy_price_adj,
            "highest": buy_price_adj, "score": data.get("score", 0),
            "structure": data.get("structure", 0),
            "sweep_level": data.get("sweep_level"),
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
        _atomic_write_json(path, state)
        return _ok(
            message=f"买入 {name} {code}: {shares}股 @{buy_price_adj:.2f}",
            shares=shares, price=buy_price_adj, cost=total_cost,
        )
    except Exception as e:
        return _err(f"保存失败: {e}")


@router.get("/stock/{code}/indicators")
def get_stock_indicators(code: str) -> dict:
    """Return computed indicators for a stock."""
    db = _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        cur = db.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(daily_kline)").fetchall()}
        date_col = "trade_date" if "trade_date" in cols else "date"
        cur.execute(
            f"SELECT {date_col}, open, high, low, close, volume FROM daily_kline "
            f"WHERE code = ? ORDER BY {date_col} DESC LIMIT 120",
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

    from data.tencent_quotes import fetch_detail

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
    from data.tencent_quotes import fetch_raw
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
    from data.tencent_quotes import add_prefix, fetch_detail

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
    tdx_script = _PROJECT_ROOT / "data" / "update_tdx_daily.py"
    if tdx_script.exists():
        try:
            result = subprocess.run(
                ["python", str(tdx_script)],
                capture_output=True, text=True, timeout=600,
                cwd=str(_PROJECT_ROOT),
            )
            stdout = result.stdout or ""
            if result.returncode == 0 and "处理完成" in stdout:
                return _ok(method="tdx_zip", message=stdout.strip().split("\n")[-1])
            # Fallback to Tencent
        except subprocess.TimeoutExpired as e:
            e.process.kill()
            e.process.wait()
            _log.warning("update_data: TDX zip timed out")
        except Exception:
            _log.warning("update_data: TDX zip failed", exc_info=True)

    # Fallback: Tencent via utils.update
    try:
        from data.update import step_tencent
        from utils.db import connect_db
        from utils.config import get_date_col
        conn = connect_db()
        date_col, is_int = get_date_col()
        total = step_tencent(conn, date_col, is_int)
        conn.close()
        return _ok(method="tencent", message=f"Tencent fallback completed: {total} rows")
    except Exception as e:
        _log.warning("Tencent fallback failed: %s", e)

    return _err("No update script found or all methods failed", method="none")


# ---------------------------------------------------------------------------
# Trade History (交易记录)
# ---------------------------------------------------------------------------

@router.post("/run-script")
def run_script(data: dict):
    """Run a trading script in background thread, return task id."""
    script = data.get("script", "")
    scripts = {
        "fibonacci": "strategies/daily_check.py",
        "trend": "strategies/daily_check_trend.py",
        "ict": "strategies/ict_scan_fast.py",
        "stops": "-m utils stops",
        "review": "analysis/generate_review.py",
        "review_v5": "analysis/generate_review.py",
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

    # 支持前端传递额外参数（如日期）
    extra_args = data.get("args", "")
    if extra_args:
        args.append(str(extra_args))

    # 验证脚本路径安全
    script_path = _PROJECT_ROOT / cmd if not cmd.startswith("-m") else None
    if script_path and not script_path.exists():
        output_file.write_text(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: 脚本文件不存在\n", encoding="utf-8")
        return {"task_id": task_id}

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # 确保子进程能找到项目根目录的模块
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_PROJECT_ROOT) + (os.pathsep + existing_path if existing_path else "")

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
def get_trades() -> dict:
    """Return trade history from paper trading state (newest first)."""
    state = _read_json(_PAPER_DIR / "paper_trading_state.json")
    history = sorted(state.get("history", []), key=lambda x: x.get("date", ""), reverse=True)
    return {"history": history}


@router.get("/trades/v5")
def get_trades_trend() -> dict:
    """Return V5 trade history (newest first)."""
    state = _read_json(_PAPER_DIR / "paper_trading_state_trend.json")
    history = sorted(state.get("history", []), key=lambda x: x.get("date", ""), reverse=True)
    return {"history": history}


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
            f"SELECT code, auction_vol, auction_price FROM auction WHERE date=? AND code IN ({auction_placeholders})",
            [today_date] + search_codes,
        ).fetchall()
        today_map = {r[0]: {"today_vol": r[1], "auction_price": r[2]} for r in today_rows}

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
        from trading.trade_journal import TradeJournal
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
        from trading.trade_journal import TradeJournal
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
        return _ok()
    except Exception as e:
        return _err(str(e))


@router.post("/journal/close")
def close_trade(data: dict) -> dict:
    """Close a trade in journal."""
    try:
        from trading.trade_journal import TradeJournal
        tj = TradeJournal()
        tj.close_trade(
            code=data.get("code", ""),
            exit_price=data.get("exit_price", 0),
            exit_reason=data.get("exit_reason", ""),
        )
        return _ok()
    except Exception as e:
        return _err(str(e))


@router.get("/journal/weekly")
def weekly_report() -> dict:
    """Get weekly trade report."""
    try:
        from trading.trade_journal import TradeJournal
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
        from analysis.llm_analyzer import analyze_stocks

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
        from analysis.backtest_eval import evaluate_picks
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
        from analysis.news_search import get_stock_news

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
        from analysis.iwencai import IwencaiClient
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
        from data.sector_utils import get_industry_map
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
            return _ok()
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Review Report (复盘报告)
# ---------------------------------------------------------------------------

@router.get("/review-report")
def get_review_report(date: str = "") -> dict:
    """Return the generated review report markdown content."""
    report_date = date if date else datetime.now().strftime("%Y-%m-%d")
    safe_name = Path(report_date).name
    for report_dir in (_PROJECT_ROOT / "reports" / "output", _PROJECT_ROOT / "reports"):
        if not report_dir.exists():
            continue
        for pattern in (f"{safe_name}.md", f"review_{safe_name}.md", f"{safe_name}_review.md"):
            report_file = report_dir / pattern
            if report_file.exists() and report_file.parent == report_dir:
                return {"content": report_file.read_text(encoding="utf-8")}
    return {"content": ""}


# ---------------------------------------------------------------------------
# Auction Board (集合竞价看板)
# ---------------------------------------------------------------------------

def _import_auction_excel(db, today_str: str) -> int:
    """Try to import auction data from Excel file in project root.

    Looks for 竞价数据_YYYY-MM-DD.xlsx, imports into auction table.
    Returns number of rows imported, or 0 if no file / import failed.
    """
    xlsx = _PROJECT_ROOT / f'竞价数据_{today_str}.xlsx'
    if not xlsx.exists():
        return 0
    try:
        import pandas as pd
        df = pd.read_excel(str(xlsx))
        cur = db.cursor()
        imported = 0
        for _, row in df.iterrows():
            code = str(row.get('代码', '')).strip()
            if not code:
                continue
            name = str(row.get('名称', ''))
            vol = int(row.get('竞价量(手)', 0)) * 100  # 手→股
            amount = float(row.get('竞价额(万元)', 0)) * 10000  # 万元→元
            open_px = float(row.get('开盘价', 0))
            prev_close = float(row.get('昨收', 0))
            collect_time = str(row.get('采集时间', ''))
            # Excel没有竞价价列，用开盘价近似
            price = open_px
            cur.execute(
                "INSERT OR REPLACE INTO auction (date, code, name, auction_vol, auction_amount, auction_price, open_price, collect_time, prev_close) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (today_str, code, name, vol, amount, price, open_px, collect_time, prev_close)
            )
            imported += 1
        db.commit()
        _log.info("imported %d auction rows from %s", imported, xlsx.name)
        return imported
    except Exception as ex:
        _log.warning("auction Excel import failed: %s", ex)
        return 0


def _check_auction_time() -> tuple[bool, dict | None]:
    """Check if auction collection is allowed.

    Returns (blocked, response). If blocked, response contains the payload to return.
    After 09:30, checks DB first; if empty, tries importing from Excel file.
    """
    now = datetime.now()
    after_cutoff = now.hour > 9 or (now.hour == 9 and now.minute >= 30)
    if not after_cutoff:
        return False, None

    db = _get_db()
    if db is None:
        return True, _err("no database")
    try:
        today_str = date.today().isoformat()
        cur = db.cursor()
        existing = cur.execute("SELECT COUNT(*) FROM auction WHERE date=?", (today_str,)).fetchone()[0]
        if existing > 0:
            return True, _ok(count=existing, status="exists")
        # DB没数据，尝试从Excel导入
        imported = _import_auction_excel(db, today_str)
        if imported > 0:
            return True, _ok(count=imported, status="imported")
        return True, _err("今日尚无竞价数据（09:30后无法采集）", status="no_data")
    finally:
        db.close()


@router.post("/auction/collect")
def collect_auction_data():
    """Collect auction data from Tencent for all stocks and store in DB.

    Only collects during auction period (09:15~09:30). After 09:30, returns
    existing data if available. Before 09:15, rejects because auction hasn't started.
    """
    now = datetime.now()
    minute_of_day = now.hour * 60 + now.minute
    if minute_of_day < 9 * 60 + 15:
        return _err(f"竞价尚未开始（当前{now.strftime('%H:%M')}，09:15后才能采集）", status="too_early")

    blocked, resp = _check_auction_time()
    if blocked:
        return resp

    db = _get_db()
    if db is None:
        return _err("no database")
    today_str = date.today().isoformat()
    try:
        from data.tencent_quotes import fetch_raw, _parse_basic, add_prefix
        row = _latest_trade_date(db)
        if not row:
            return _err("no kline data")
        latest_date = row

        cur = db.cursor()
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
            if vol <= 0:
                continue
            amount = basic["amount"]
            price = basic["price"]
            open_px = basic["open"]
            name = fields[1]
            prev_close = float(fields[4]) if fields[4] else 0
            ratio = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
            try:
                bare_code = code[2:] if code.startswith(("sh", "sz", "bj")) else code
                cur.execute(
                    "INSERT OR REPLACE INTO auction (date, code, name, auction_vol, auction_amount, auction_price, open_price, collect_time, prev_close) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (today_str, bare_code, name, vol, amount, price, open_px, datetime.now().strftime("%H:%M:%S"), prev_close)
                )
                collected += 1
            except Exception:
                _log.warning("auction insert failed for %s", code, exc_info=True)
        db.commit()
        # 导出 Excel
        try:
            import pandas as pd
            rows = cur.execute(
                "SELECT date, code, name, auction_vol, auction_amount, auction_price, open_price, collect_time, prev_close FROM auction WHERE date=? ORDER BY auction_vol DESC",
                (today_str,)
            ).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=['日期', '代码', '名称', '竞价量(手)', '竞价额(元)', '竞价价', '开盘价', '采集时间', '昨收'])
                df['竞价额(元)'] = (df['竞价额(元)'] / 10000).round(2)
                df = df.rename(columns={'竞价额(元)': '竞价额(万元)'})
                df = df.drop(columns=['竞价价'])
                out = _PROJECT_ROOT / f'竞价数据_{today_str}.xlsx'
                df.to_excel(str(out), index=False, sheet_name='竞价数据')
                _log.info("auction Excel exported: %s", out.name)
        except Exception as ex:
            _log.warning("auction Excel export failed: %s", ex)
        return _ok(count=collected, status="collected")
    except Exception as e:
        _log.warning("auction collect failed", exc_info=True)
        return _err(str(e))
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
        cur.execute("SELECT date, COUNT(*), COALESCE(SUM(auction_vol), 0) FROM auction GROUP BY date ORDER BY date DESC")
        dates = [{"date": r[0], "count": r[1], "total_vol": r[2]} for r in cur.fetchall()]
        return {"dates": dates}
    except Exception as e:
        _log.warning("auction dates failed", exc_info=True)
        return {"dates": []}
    finally:
        db.close()


@router.post("/auction/snapshot")
def register_auction_snapshot_task():
    """Register Windows scheduled task for auction snapshot collection (9:15/9:18/9:20/9:26)."""
    import subprocess
    try:
        snapshot_script = str(_PROJECT_ROOT / "data" / "snapshot_collector.py")
        import sys as _sys
        python_exe = _sys.executable
        ps_cmd = (
            f'$taskName = "AuctionSnapshot"; '
            f'$action = New-ScheduledTaskAction -Execute "{python_exe}" '
            f'-Argument "`\"{snapshot_script}`\" collect" '
            f'-WorkingDirectory "{_PROJECT_ROOT}"; '
            f'$t1 = New-ScheduledTaskTrigger -Daily -At "09:15"; '
            f'$t2 = New-ScheduledTaskTrigger -Daily -At "09:20"; '
            f'$t3 = New-ScheduledTaskTrigger -Daily -At "09:23"; '
            f'$t4 = New-ScheduledTaskTrigger -Daily -At "09:25"; '
            f'Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; '
            f'Register-ScheduledTask -TaskName $taskName -Action $action '
            f'-Trigger $t1,$t2,$t3,$t4 -Description "AuctionSnapshot(9:15/9:20/9:23/9:26)" -RunLevel Limited'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return _ok(status="registered", message="竞价快照定时任务已注册 (9:14/9:17/9:19/9:26)")
        else:
            return _err(f"注册失败: {result.stderr or result.stdout}")
    except Exception as e:
        _log.warning("register auction snapshot task failed", exc_info=True)
        return _err(str(e))


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
        cur.execute("SELECT code, name, auction_vol, auction_amount, auction_price, open_price FROM auction WHERE date=? ORDER BY auction_vol DESC LIMIT ?", (date, limit))
        rows = cur.fetchall()
        stocks = []
        for r in rows:
            stocks.append({
                "code": r[0], "name": r[1], "auction_vol": r[2], "auction_amount": r[3],
                "auction_price": r[4], "open_price": r[5],
            })
        count = len(stocks)
        total_vol = sum(s["auction_vol"] for s in stocks)
        total_amount = sum(s["auction_amount"] for s in stocks)
        leaders = sorted(stocks, key=lambda s: s["auction_vol"], reverse=True)[:5]
        return {
            "stocks": stocks,
            "leaders": leaders,
            "stats": {"count": count, "total_vol": total_vol, "total_amount": total_amount},
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
        cur.execute("SELECT code, name, auction_vol, auction_price, prev_close FROM auction WHERE date=?", (date1,))
        d1_map = {}
        for r in cur.fetchall():
            d1_map[r[0]] = {"name": r[1], "vol": r[2], "price": r[3], "prev_close": r[4] or 0}
        cur.execute("SELECT code, name, auction_vol, auction_price, prev_close FROM auction WHERE date=?", (date2,))
        d2_map = {}
        for r in cur.fetchall():
            d2_map[r[0]] = {"name": r[1], "vol": r[2], "price": r[3], "prev_close": r[4] or 0}
        _log.warning("compare d1=%d d2=%d db=%s", len(d1_map), len(d2_map), db)
        if "002607" in d1_map:
            _log.warning("002607 d1: %s", d1_map["002607"])

        all_codes = set(d1_map) | set(d2_map)
        if not all_codes:
            return {"date1": date1, "date2": date2, "gainers": [], "losers": [],
                    "increase": 0, "decrease": 0, "total": 0}

        # Compute diff list first (no DB needed)
        diff = []
        for code in all_codes:
            v1 = d1_map.get(code, {}).get("vol", 0) or 0
            v2 = d2_map.get(code, {}).get("vol", 0) or 0
            name = d1_map.get(code, d2_map.get(code, {})).get("name", "")
            chg = v2 - v1
            pct = round((v2 - v1) / v1 * 100, 2) if v1 else 0
            info = d1_map.get(code) or d2_map.get(code) or {}
            diff.append({
                "code": code, "name": name,
                "vol_today": v2, "vol_prev": v1,
                "vol_chg": chg, "vol_pct": pct,
                "price_today": info.get("price", 0) or 0,
            })

        diff.sort(key=lambda x: x["vol_chg"], reverse=True)
        gainers = [d for d in diff if d["vol_chg"] > 0][:top]
        losers = [d for d in diff if d["vol_chg"] < 0][:top]
        increase = sum(1 for d in diff if d["vol_chg"] > 0)
        decrease = sum(1 for d in diff if d["vol_chg"] < 0)

        # 竞价涨幅 = (竞价价 - 昨收) / 昨收，优先用 date1 数据
        for d in gainers + losers:
            code = d["code"]
            info = d1_map.get(code) or d2_map.get(code) or {}
            auction_price = info.get("price", 0) or 0
            pc = info.get("prev_close", 0) or 0
            d["auction_chg_today"] = round((auction_price - pc) / pc * 100, 2) if pc and auction_price else None
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


@router.get("/auction/concept-analysis")
def get_auction_concept_analysis(date: str = "", source: str = "industry"):
    """Return sector-level auction analysis (超预期/锚点/中军/弹性/最高板).
    
    Args:
        date: 日期 YYYY-MM-DD
        source: 'industry' 东财行业分组, 'concept' 概念板块分组
    """
    _log.warning("[concept-analysis] hit endpoint date=%s source=%s", date, source)
    if not date:
        db = _get_db()
        if db:
            try:
                r = db.execute("SELECT DISTINCT date FROM auction ORDER BY date DESC LIMIT 1").fetchone()
                if r:
                    date = r[0]
            except Exception:
                pass
            finally:
                db.close()
    if not date:
        _log.warning("[concept-analysis] no date, returning empty")
        return {"date": "", "concepts": []}
    try:
        _log.warning("[concept-analysis] importing analyze_to_json...")
        from data.auction_concept_analysis import analyze_to_json
        result = analyze_to_json(date, top_concepts=50, source=source)
        _log.warning("[concept-analysis] success, concepts=%d", len(result.get("concepts", [])))
        return result
    except Exception as e:
        _log.warning("[concept-analysis] FAILED for %s: %s", date, e, exc_info=True)
        return {"date": date, "concepts": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Market Ladder (连板梯队)
# ---------------------------------------------------------------------------

_LADDER_CACHE_DIR = _PAPER_DIR

def _ladder_cache_path(today_compact: str) -> Path:
    return _LADDER_CACHE_DIR / f"ladder_cache_{today_compact}.json"


@router.get("/market/ladder")
def get_market_ladder():
    """Get limit-up ladder analysis via iwencai, with daily file cache."""
    today_compact = date.today().strftime("%Y%m%d")
    cache_path = _ladder_cache_path(today_compact)

    # Serve from cache if available
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached
    except Exception:
        pass

    # Cache miss — fetch from iwencai
    try:
        if not os.environ.get("IWENCAI_API_KEY"):
            root_env = _PROJECT_ROOT / ".env"
            if root_env.exists():
                for line in root_env.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "IWENCAI_API_KEY":
                            os.environ[k.strip()] = v.strip()
                            break

        from analysis.iwencai import query_data

        raw = query_data(
            "今日涨停股票 剔除ST 剔除退市 股票代码 股票简称 收盘价 最新涨跌幅 连续涨停天数 涨停原因 成交额"
        )
        if not raw:
            result = {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": "暂无数据"}
            return result

        ladder = []
        for row in raw:
            code = (row.get("股票代码", "") or "").replace(".SZ", "").replace(".SH", "").strip()
            name = row.get("股票简称", "") or ""
            if not code or not name:
                continue

            price_str = row.get(f"收盘价[{today_compact}]") or row.get("收盘价", "0")
            chg = row.get("最新涨跌幅") or 0
            board_raw = row.get(f"连续涨停天数[{today_compact}]") or row.get("连续涨停天数", 1)
            amount_str = row.get(f"成交额[{today_compact}]") or row.get("成交额", "0")
            reason = row.get(f"涨停原因[{today_compact}]") or row.get("涨停原因", "")

            concepts = [c.strip() for c in reason.split("+") if c.strip()] if reason else []

            try:
                price = float(price_str) if price_str else 0
            except (ValueError, TypeError):
                price = 0
            try:
                board = int(float(board_raw))
            except (ValueError, TypeError):
                board = 1
            try:
                amount = float(amount_str)
            except (ValueError, TypeError):
                amount = 0
            try:
                chg = float(chg)
            except (ValueError, TypeError):
                chg = 0

            ladder.append({
                "code": code,
                "name": name,
                "price": price,
                "chg_pct": chg,
                "board": board,
                "amount": amount,
                "volume": 0,
                "concepts": concepts,
            })

        ladder.sort(key=lambda s: (-s["board"], -s["chg_pct"]))

        by_board = {}
        for s in ladder:
            by_board.setdefault(str(s["board"]), []).append(s)

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

        result = {
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

        # Write cache
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        return result
    except Exception as e:
        _log.warning("market ladder failed", exc_info=True)
        return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": str(e)}


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
        from data.tencent_quotes import fetch_raw, _parse_basic, add_prefix

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
        from data.tencent_quotes import add_prefix
        from indicators.fibonacci_formula import find_latest_cycle, fibonacci_price, fibonacci_exit
        from indicators.indicators import calc_rsi
        from analysis.runaway_price import calc_runaway_price

        # Ensure code has prefix for DB queries (DB stores sz000001 / sh600519)
        prefixed = add_prefix(code)
        db_code = prefixed

        # Get kline data
        cur = db.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(daily_kline)").fetchall()}
        date_col = "trade_date" if "trade_date" in cols else "date"
        cur.execute(f"SELECT {date_col}, open, high, low, close, volume FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 120", (db_code,))
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
            from data.tencent_quotes import fetch_detail
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
    csv_path = str(_PAPER_DIR / "shadow_account_input.csv")
    try:
        result = subprocess.run(
            [_sys.executable, "-m", "utils.paper_to_shadow"],
            capture_output=True, text=True, timeout=30,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            return _err(f"转换失败: {result.stderr[:500]}")
    except Exception as e:
        return _err(f"转换异常: {e}")

    # Step 2: Extract shadow profile + render report via Vibe-Trading agent
    agent_dir = Path(__file__).resolve().parent.parent.parent
    script = agent_dir / "src" / "shadow_account" / "_analyze_script.py"
    try:
        result = subprocess.run(
            [_sys.executable, str(script), "--csv", csv_path],
            capture_output=True, text=True, timeout=120,
            cwd=str(agent_dir),
            env={**os.environ, "PYTHONPATH": str(agent_dir)},
        )
        if result.returncode != 0:
            return _err(f"分析失败: {result.stderr[:500]}")
        summary = json.loads(result.stdout.strip().split("\n")[-1])
        return _ok(**summary)
    except subprocess.TimeoutExpired as e:
        e.process.kill()
        e.process.wait()
        return _err("分析超时（>120s）")
    except Exception as e:
        return _err(f"分析异常: {e}")


@router.get("/shadow/report/{shadow_id}")
def shadow_report(shadow_id: str):
    """Return the shadow account HTML report content."""
    import re
    if not re.match(r"^shadow_[0-9a-f]{8}$", shadow_id):
        return _err("invalid shadow_id")
    report_path = Path.home() / ".vibe-trading" / "shadow_reports" / f"{shadow_id}.html"
    if not report_path.exists():
        return _err("报告不存在，请先运行分析")
    html = report_path.read_text(encoding="utf-8")
    return _ok(html=html)


@router.get("/smc/{code}")
def get_smc_analysis(code: str):
    """返回个股SMC分析数据（K线 + BOS/ChoCH/FVG/OB/Sweep标注）"""
    import sys as _sys
    _trading_root = str(_PROJECT_ROOT)
    if _trading_root not in _sys.path:
        _sys.path.insert(0, _trading_root)

    try:
        from strategies.ict_strategy import (
            _fetch_kline, smc_pipeline, swing_points, calc_bos_choch,
            calc_order_blocks, calc_fvg, calc_liquidity_sweep,
            detect_3_1_structure, calc_ote, calc_trend_continuous
        )
    except ImportError as e:
        return _err(f"ict_strategy不可用: {e}")

    db = _get_db()
    if db is None:
        return _err("无法连接数据库")

    try:
        date_col = "trade_date"
        cols = {r[1] for r in db.execute("PRAGMA table_info(daily_kline)").fetchall()}
        if "date" in cols and "trade_date" not in cols:
            date_col = "date"

        limit = 120
        sql = f"""SELECT {date_col} as date, open, high, low, close, volume
                  FROM daily_kline WHERE code = ? ORDER BY {date_col} DESC LIMIT ?"""
        import pandas as pd
        df = pd.read_sql(sql, db, params=[code, limit])
        db.close()

        if df.empty:
            return _err(f"无数据: {code}")

        is_int = date_col == "trade_date"
        if is_int:
            df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
        else:
            df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # 运行完整SMC管线
        result, major_ob, minor_ob, fvg_df = smc_pipeline(df)

        # 提取K线数据
        klines = []
        for i in range(len(result)):
            row = result.iloc[i]
            klines.append({
                "time": row["date"].strftime("%Y-%m-%d"),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(row["volume"]),
            })

        # 提取BOS/ChoCH信号
        signals = []
        for i in range(len(result)):
            row = result.iloc[i]
            bos = row.get("bos", 0)
            choch = row.get("choch", 0)
            if bos != 0:
                signals.append({
                    "time": row["date"].strftime("%Y-%m-%d"),
                    "type": "BOS",
                    "direction": "bullish" if bos > 0 else "bearish",
                    "price": round(float(row["high"] if bos > 0 else row["low"]), 2),
                })
            if choch != 0:
                signals.append({
                    "time": row["date"].strftime("%Y-%m-%d"),
                    "type": "ChoCH",
                    "direction": "bullish" if choch > 0 else "bearish",
                    "price": round(float(row["high"] if choch > 0 else row["low"]), 2),
                })

        # 提取Sweep信号
        sweeps = []
        if "sweep" in result.columns:
            for i in range(len(result)):
                row = result.iloc[i]
                sw = row.get("sweep", 0)
                if sw != 0:
                    sweeps.append({
                        "time": row["date"].strftime("%Y-%m-%d"),
                        "direction": "bullish" if sw > 0 else "bearish",
                        "price": round(float(row["low"] if sw > 0 else row["high"]), 2),
                    })

        # 提取FVG区间
        fvg_zones = []
        if "fvg_type" in result.columns:
            for i in range(len(result)):
                row = result.iloc[i]
                ft = row.get("fvg_type", 0)
                if ft != 0:
                    fvg_zones.append({
                        "time": row["date"].strftime("%Y-%m-%d"),
                        "type": "bullish" if ft > 0 else "bearish",
                        "top": round(float(row.get("fvg_top", 0)), 2),
                        "bottom": round(float(row.get("fvg_bottom", 0)), 2),
                    })

        # 提取OB区间
        ob_zones = []
        if major_ob is not None and not major_ob.empty:
            for _, ob in major_ob.iterrows():
                try:
                    ob_date = result.loc[ob["ob_idx"], "date"].strftime("%Y-%m-%d")
                    expiry_date = result.loc[min(ob["expiry_idx"], len(result)-1), "date"].strftime("%Y-%m-%d")
                    ob_zones.append({
                        "start": ob_date,
                        "end": expiry_date,
                        "top": round(float(ob["ob_top"]), 2),
                        "bottom": round(float(ob["ob_bottom"]), 2),
                        "type": "major",
                    })
                except Exception:
                    pass

        # 提取OTE区间
        ote_zones = []
        if "ote_high" in result.columns:
            last_ote_high = None
            last_ote_low = None
            last_ote_start = None
            for i in range(len(result)):
                row = result.iloc[i]
                oh = row.get("ote_high", None)
                ol = row.get("ote_low", None)
                if pd.notna(oh) and pd.notna(ol):
                    if last_ote_high is None or oh != last_ote_high:
                        if last_ote_high is not None:
                            ote_zones.append({
                                "start": last_ote_start,
                                "end": result.iloc[i-1]["date"].strftime("%Y-%m-%d"),
                                "top": round(float(last_ote_high), 2),
                                "bottom": round(float(last_ote_low), 2),
                            })
                        last_ote_high = oh
                        last_ote_low = ol
                        last_ote_start = row["date"].strftime("%Y-%m-%d")
            if last_ote_high is not None:
                ote_zones.append({
                    "start": last_ote_start,
                    "end": result.iloc[-1]["date"].strftime("%Y-%m-%d"),
                    "top": round(float(last_ote_high), 2),
                    "bottom": round(float(last_ote_low), 2),
                })

        # 生成当前分析建议
        last_row = result.iloc[-1]
        last_close = float(last_row["close"])
        last_date = last_row["date"].strftime("%Y-%m-%d")
        trend = int(last_row.get("trend", 0))
        ma20 = float(last_row.get("ma20", 0)) if pd.notna(last_row.get("ma20")) else 0
        ma60 = float(last_row.get("ma60", 0)) if pd.notna(last_row.get("ma60")) else 0
        rsi = float(last_row.get("rsi", 0)) if pd.notna(last_row.get("rsi")) else 0
        bos_last = int(last_row.get("bos", 0))
        choch_last = int(last_row.get("choch", 0))

        # 近期信号统计
        recent_signals = signals[-5:] if len(signals) >= 5 else signals
        recent_bull_bos = sum(1 for s in signals[-10:] if s["type"] == "BOS" and s["direction"] == "bullish")
        recent_bear_bos = sum(1 for s in signals[-10:] if s["type"] == "BOS" and s["direction"] == "bearish")
        recent_bull_choch = sum(1 for s in signals[-10:] if s["type"] == "ChoCH" and s["direction"] == "bullish")
        recent_bear_choch = sum(1 for s in signals[-10:] if s["type"] == "ChoCH" and s["direction"] == "bearish")

        # 分析建议
        analysis_parts = []
        if trend > 0:
            analysis_parts.append("当前处于上升趋势（HH/HL结构）")
        elif trend < 0:
            analysis_parts.append("当前处于下降趋势（LH/LL结构）")
        else:
            analysis_parts.append("趋势不明朗，处于震荡区间")

        if ma20 > 0 and ma60 > 0:
            if ma20 > ma60:
                analysis_parts.append(f"MA20({ma20:.2f}) > MA60({ma60:.2f})，均线多头排列")
            else:
                analysis_parts.append(f"MA20({ma20:.2f}) < MA60({ma60:.2f})，均线空头排列")

        if rsi > 0:
            if rsi > 70:
                analysis_parts.append(f"RSI={rsi:.1f}，超买区域，注意回调风险")
            elif rsi < 30:
                analysis_parts.append(f"RSI={rsi:.1f}，超卖区域，可能存在反弹机会")
            else:
                analysis_parts.append(f"RSI={rsi:.1f}，处于正常区间")

        if recent_bull_bos > recent_bear_bos:
            analysis_parts.append(f"近期多头BOS({recent_bull_bos}次)多于空头BOS({recent_bear_bos}次)，结构偏多")
        elif recent_bear_bos > recent_bull_bos:
            analysis_parts.append(f"近期空头BOS({recent_bear_bos}次)多于多头BOS({recent_bull_bos}次)，结构偏空")

        if fvg_zones:
            last_fvg = fvg_zones[-1]
            if last_fvg["type"] == "bullish" and last_close >= last_fvg["bottom"]:
                analysis_parts.append(f"价格在看涨FVG区间内({last_fvg['bottom']:.2f}-{last_fvg['top']:.2f})，存在支撑")
            elif last_fvg["type"] == "bearish" and last_close <= last_fvg["top"]:
                analysis_parts.append(f"价格在看跌FVG区间内({last_fvg['bottom']:.2f}-{last_fvg['top']:.2f})，存在压力")

        if ob_zones:
            last_ob = ob_zones[-1]
            if last_close >= last_ob["bottom"] and last_close <= last_ob["top"]:
                analysis_parts.append(f"价格在订单块(OB)区间内({last_ob['bottom']:.2f}-{last_ob['top']:.2f})，机构关注区域")

        # 综合建议
        if trend > 0 and ma20 > ma60 and rsi < 55 and recent_bull_bos > 0:
            suggestion = "结构偏多，可关注做多机会，注意FVG/OB支撑位入场"
        elif trend < 0 or ma20 < ma60:
            suggestion = "结构偏空，建议观望等待趋势反转信号"
        elif rsi > 70:
            suggestion = "RSI超买，短期注意回调风险"
        elif rsi < 30:
            suggestion = "RSI超卖，可能存在反弹机会，但需等待结构确认"
        else:
            suggestion = "趋势不明，建议观望等待方向明确"

        return _ok(
            klines=klines,
            signals=signals,
            sweeps=sweeps,
            fvg_zones=fvg_zones,
            ob_zones=ob_zones,
            ote_zones=ote_zones,
            analysis={
                "date": last_date,
                "price": last_close,
                "trend": trend,
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "rsi": round(rsi, 1),
                "recent_bull_bos": recent_bull_bos,
                "recent_bear_bos": recent_bear_bos,
                "points": analysis_parts,
                "suggestion": suggestion,
            },
        )
    except Exception as exc:
        _log.error("get_smc_analysis failed: %s", exc, exc_info=True)
        return _err(str(exc))


@router.get("/shadow/list")
def shadow_list():
    """List all existing shadow account reports."""
    reports_dir = Path.home() / ".vibe-trading" / "shadow_reports"
    if not reports_dir.exists():
        return _ok(reports=[])
    reports = []
    for f in sorted(reports_dir.glob("shadow_*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        shadow_id = f.stem
        reports.append({
            "shadow_id": shadow_id,
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return _ok(reports=reports)


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

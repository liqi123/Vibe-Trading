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
_AI_REPORT_DIR = _PROJECT_ROOT / "reports" / "output" / "auction_ai"

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


def _open_db_readonly(path: str) -> sqlite3.Connection | None:
    """以 immutable 只读模式打开 SQLite，绕过 sandbox 对 -wal/-journal 的拦截。

    immutable=1 告知 SQLite 文件不会被修改，故不打开 WAL/journal，
    仅读主 .db 文件——适合只读 API。主库写操作由 `python -m utils update` 独立连接处理。
    """
    uri = "file:" + str(path).replace("\\", "/").lstrip("/") + "?immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.execute("SELECT 1").fetchone()  # 验证可读
        return conn
    except Exception:
        return None


def _get_db(writable: bool = False) -> sqlite3.Connection | None:
    """Open the SQLite database holding daily_kline.

    候选路径优先级: utils.config.DB_PATH > G:/E: 盘 > 项目本地 tdx_daily.db > 旧 tdx_data.db。
    - 只读（默认）: 用 immutable=1 URI 打开，避开 sandbox 对 WAL 的拦截，并按 max date 选最新库。
    - 可写（writable=True）: 用普通 sqlite3.connect，选第一个能打开且有 daily_kline 表的库
      （sandbox 下 G:\\ 可能因 WAL 打不开，会回退到本地可写副本）。
    """
    candidates = [
        r"G:\tdx_data\tdx_daily.db",
        r"E:\DataBase\tdx_data.db",
        str(_PROJECT_ROOT / "tdx_daily.db"),
        str(_PROJECT_ROOT / "tdx_daily_writable.db"),   # 可写副本（G盘WAL锁死时，update 会写到这里）
        str(_DB_PATH),
    ]
    # 优先从 utils.config 拿 DB_PATH（项目规范）
    try:
        from utils.config import DB_PATH
        p = Path(str(DB_PATH))
        if p.exists():
            candidates.insert(0, str(p))
    except Exception:
        pass

    if writable:
        # 可写模式: 普通 connect，选第一个有 daily_kline 表的库
        for c in candidates:
            p = Path(c)
            if not p.exists():
                continue
            try:
                conn = sqlite3.connect(str(p), timeout=10)
                tabs = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                if "daily_kline" in tabs:
                    return conn
                conn.close()
            except Exception:
                continue
        return None

    # 只读模式: immutable=1 + 新鲜度比较
    best_conn: sqlite3.Connection | None = None
    best_max = None
    for c in candidates:
        p = Path(c)
        if not p.exists():
            continue
        conn = _open_db_readonly(c)
        if conn is None:
            continue
        try:
            tabs = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "daily_kline" not in tabs:
                conn.close()
                continue
            cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_kline)").fetchall()}
            dc = "trade_date" if "trade_date" in cols else "date"
            mx = conn.execute(f"SELECT MAX({dc}) FROM daily_kline").fetchone()[0]
            if mx is None:
                conn.close()
                continue
            if best_max is None or mx > best_max:
                if best_conn is not None:
                    best_conn.close()
                best_conn = conn
                best_max = mx
            else:
                conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            continue
    return best_conn


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
    """Return expectation state for all positions, with live prev_close + MA from DB."""
    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    for p in positions:
        p.setdefault("category", "holding")
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

            # 优先从auction表获取prev_close
            try:
                auction_row = db.execute(
                    "SELECT prev_close FROM auction WHERE code=? ORDER BY date DESC LIMIT 1",
                    (bare_code,)
                ).fetchone()
            except sqlite3.OperationalError:
                auction_row = None
            if auction_row and auction_row[0]:
                p["prev_close"] = auction_row[0]
            else:
                row = db.execute(
                    f"SELECT close FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 1",
                    (code,)
                ).fetchone()
                if row and row[0]:
                    p["prev_close"] = row[0]

            # MA5 / MA10 / MA20
            try:
                ma_rows = db.execute(
                    f"SELECT close FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 20",
                    (code,)
                ).fetchall()
                closes = [r[0] for r in ma_rows if r[0]]
                if len(closes) >= 5:
                    p["ma5"] = round(sum(closes[:5]) / 5, 2)
                if len(closes) >= 10:
                    p["ma10"] = round(sum(closes[:10]) / 10, 2)
                if len(closes) >= 20:
                    p["ma20"] = round(sum(closes[:20]) / 20, 2)
            except Exception:
                pass
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

    # 分类: observation=观察股, holding=持仓股(默认)
    category = data.get("category", "holding")
    if category not in ("observation", "holding"):
        category = "holding"

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
            # 已存在: 若分类不同则移动到目标分类, 否则提示已存在
            if p.get("category", "holding") != category:
                p["category"] = category
                state["positions"] = positions
                _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
                return _ok(message="Moved")
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
        "category": category,
    })
    state["positions"] = positions

    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


@router.post("/expectations/update-prices")
def update_expectation_prices(data: dict):
    """Update cost_price, name, note for a stock."""
    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])

    for p in positions:
        if p.get("code") == code:
            if "cost_price" in data:
                p["cost_price"] = data.get("cost_price", 0)
            if "name" in data:
                p["name"] = data.get("name", "")
            if "note" in data:
                p["note"] = data.get("note", "")
            break

    state["positions"] = positions
    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok()


@router.post("/expectations/update-support-resistance")
def update_support_resistance(data: dict):
    """计算个股支撑/压力位(SMC结构位: 订单块/摆动高低点)并写入 note 的固定标记段。

    写入格式: note 中出现【支撑压力】开头的行会被整体替换，其余用户备注文字原样保留。
    """
    import sys as _sys
    import re
    import pandas as pd

    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    _trading_root = str(_PROJECT_ROOT)
    if _trading_root not in _sys.path:
        _sys.path.insert(0, _trading_root)

    try:
        from strategies.ict.ict_indicators import smc_pipeline, swing_points
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
        df = pd.read_sql(
            f"SELECT {date_col} as date, open, high, low, close, volume "
            f"FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT 120",
            db, params=[code],
        )
    finally:
        db.close()

    if df.empty:
        return _err(f"无数据: {code}")

    if date_col == "trade_date":
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    else:
        df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    try:
        result, major_ob, minor_ob, fvg_df = smc_pipeline(df)
    except Exception as exc:
        return _err(f"SMC计算失败: {exc}")

    last_close = float(result.iloc[-1]["close"])
    support = None
    resistance = None

    # 1) 主源: major 订单块(OB)边界 — 下方最近 OB 下沿=支撑, 上方最近 OB 上沿=压力
    if major_ob is not None and not major_ob.empty:
        below = major_ob[major_ob["ob_bottom"] < last_close]
        if not below.empty:
            support = float(below["ob_bottom"].max())
        above = major_ob[major_ob["ob_top"] > last_close]
        if not above.empty:
            resistance = float(above["ob_top"].min())

    # 2) 次源: swing 摆动高低点 (若 OB 某一侧缺失)
    if support is None or resistance is None:
        try:
            base = result if "swing" in result.columns else df
            sw_df = swing_points(base, size=3)
            sw = sw_df["swing"].fillna(0).astype(int).values
            lows = sw_df["low"].values
            highs = sw_df["high"].values
            if support is None:
                cand = [float(lows[i]) for i in range(len(sw)) if sw[i] == -1 and lows[i] < last_close]
                if cand:
                    support = max(cand)
            if resistance is None:
                cand = [float(highs[i]) for i in range(len(sw)) if sw[i] == 1 and highs[i] > last_close]
                if cand:
                    resistance = min(cand)
        except Exception:
            pass

    # 3) 兜底: 滚动窗口高低点 (永远可用，确保每只票都有支撑/压力)
    if support is None:
        bl = df[df["low"] < last_close]
        if not bl.empty:
            support = float(bl["low"].max())
    if resistance is None:
        ah = df[df["high"] > last_close]
        if not ah.empty:
            resistance = float(ah["high"].min())

    if support is None and resistance is None:
        return _err("未能计算出支撑/压力位")

    # 操作建议(基于现价相对支撑/压力的位置；不重复数字，数字已在独立列展示)
    pct_s = (last_close - support) / last_close * 100 if support else None   # 支撑在现价下方，正数
    pct_r = (resistance - last_close) / last_close * 100 if resistance else None  # 压力在现价上方，正数
    if support and last_close <= support:
        advice = "已跌破支撑,观望等待企稳"
    elif resistance and last_close >= resistance:
        advice = "已突破压力,回踩确认后可跟随"
    elif pct_s is not None and pct_s <= 3:
        advice = "贴近支撑,可关注低吸/布局"
    elif pct_r is not None and pct_r <= 3:
        advice = "临近压力,建议逢高减仓/了结"
    else:
        advice = "区间震荡,支撑上方低吸、压力下方高抛,波段操作"
    advice_text = "【操作建议】" + advice

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])
    updated = False
    new_note = None
    for p in positions:
        if p.get("code") == code:
            old_note = p.get("note", "") or ""
            if re.search(r"【支撑压力】|【操作建议】", old_note):
                new_note = re.sub(r"【支撑压力】[^\n]*|【操作建议】[^\n]*", advice_text, old_note)
            else:
                new_note = (old_note + "\n" + advice_text).strip() if old_note else advice_text
            p["note"] = new_note
            # 结构化字段(供前端展示与预警高亮)
            p["support"] = support
            p["resistance"] = resistance
            updated = True
            break

    if not updated:
        return _err(f"自选股中未找到: {code}")

    state["positions"] = positions
    _atomic_write_json(_PAPER_DIR / "expectation_state.json", state)
    return _ok(code=code, support=support, resistance=resistance, note=new_note)


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
    prefix = "v1" if strategy == "fibonacci" else "trend" if strategy == "trend" else "ict" if strategy == "ict" else "sentiment"

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


# ---------- 情绪选股 AI 阶段分析 ----------

_SENT_STEP_PROMPTS = {
    1: (
        "你是A股短线情绪周期分析师。根据市场广度数据判断当前情绪周期阶段。"
        "阶段取值：冰点/启动/发酵/主升/分歧/退潮。"
        "返回严格JSON：{\"phase\": \"阶段\", \"analysis\": \"判断依据(80字内)\", \"suggestion\": \"操作建议(60字内)\"}"
    ),
    2: (
        "你是A股短线主线板块分析师。判断主线板块的强度阶段。"
        "阶段取值：无主线/启动/加速/高潮/分歧/退潮。"
        "返回严格JSON：{\"phase\": \"阶段\", \"analysis\": \"判断依据(80字内)\", \"suggestion\": \"关注主线与建议(60字内)\"}"
    ),
    3: (
        "你是A股短线个股梯队分析师。分析候选股的地位结构和参与价值。"
        "阶段取值：梯队完整/梯队断层/梯队稀疏/无梯队。"
        "返回严格JSON：{\"phase\": \"阶段\", \"analysis\": \"梯队结构分析(80字内)\", \"suggestion\": \"值得关注与需回避的个股(80字内)\"}"
    ),
    4: (
        "你是A股短线交易决策顾问。综合情绪周期、主线板块、个股梯队给出综合阶段判断和操作策略。"
        "阶段取值：积极进攻/均衡配置/防守/空仓。"
        "返回严格JSON：{\"phase\": \"阶段\", \"analysis\": \"综合判断(100字内)\", \"suggestion\": \"做不做/在哪做/做哪个(100字内)\"}"
    ),
}


def _build_sentiment_user_prompt(step: int, header: dict, candidates: list) -> str:
    """按 step 构造发给 LLM 的用户提示（精简数据避免 token 爆炸）。"""
    if step == 1:
        breadth = header.get("breadth") or {}
        data = {
            "cycle": header.get("cycle", ""),
            "breadth": {
                "limit_up": breadth.get("limit_up", 0),
                "gainer": breadth.get("gainer", 0),
                "max_streak": breadth.get("max_streak", 0),
            },
        }
        return f"市场广度数据：\n{json.dumps(data, ensure_ascii=False)}\n请判断当前情绪周期阶段。"
    if step == 2:
        mainlines = [
            {
                "concept": m.get("concept", ""),
                "score": m.get("score", 0),
                "n": m.get("n", 0),
                "zt_n": m.get("zt_n", 0),
                "max_streak": m.get("max_streak", 0),
                "avg_chg": m.get("avg_chg", 0),
            }
            for m in (header.get("mainlines") or [])[:12]
        ]
        return f"主线板块数据（共{len(header.get('mainlines') or [])}条，展示前12）：\n{json.dumps(mainlines, ensure_ascii=False)}\n请判断主线板块阶段。"
    if step == 3:
        stocks = []
        for c in candidates[:20]:
            s = c.get("stock") or {}
            stocks.append({
                "mainline": c.get("mainline", ""),
                "role": s.get("role", ""),
                "name": s.get("name", ""),
                "chg": s.get("chg", 0),
                "streak": s.get("streak", 0),
                "is_zt": s.get("is_zt", False),
            })
        return f"个股精选数据（共{len(candidates)}只，展示前20）：\n{json.dumps(stocks, ensure_ascii=False)}\n请分析梯队结构与参与价值。"
    # step 4 综合全部
    breadth = header.get("breadth") or {}
    summary = {
        "cycle": header.get("cycle", ""),
        "breadth": {k: breadth.get(k, 0) for k in ("limit_up", "gainer", "max_streak")},
        "mainline_count": len(header.get("mainlines") or []),
        "top_mainlines": [m.get("concept", "") for m in (header.get("mainlines") or [])[:5]],
        "candidate_count": len(candidates),
        "top_roles": [c.get("stock", {}).get("role", "") for c in candidates[:8]],
    }
    return f"综合数据：\n{json.dumps(summary, ensure_ascii=False)}\n请给出综合阶段判断和操作策略。"


@router.post("/sentiment/ai-analyze")
def sentiment_ai_analyze(body: dict) -> dict:
    """情绪选股 AI 阶段分析：针对某一步，调用本地/已配置 LLM 判断当前阶段。

    body: {step: 1|2|3|4, header: {...}, candidates: [...]}
    返回: {ok, step, phase, analysis, suggestion} 或 {ok:false, error}
    """
    from strategies.common.llm_client import get_llm_client, is_llm_available, load_llm_config
    from utils.logging_setup import get_run_logger
    _run_logger = get_run_logger("sentiment_ai_analyze", "ai_analysis")

    step_raw = body.get("step", 1)
    header = body.get("header") or {}
    candidates = body.get("candidates") or []
    _run_logger.info(
        "[sentiment-ai] 收到请求 step=%s header_keys=%s candidates=%d",
        step_raw, list(header.keys()), len(candidates),
    )

    _cfg = load_llm_config()
    import os as _os
    _dbg = {
        "provider": _cfg.provider, "model": _cfg.model,
        "key_len": len(_cfg.api_key), "key_prefix": _cfg.api_key[:6] if _cfg.api_key else "EMPTY",
        "base_url": _cfg.base_url,
        "env_provider": _os.environ.get("LANGCHAIN_PROVIDER", "<unset>"),
        "env_deepseek_key": bool(_os.environ.get("DEEPSEEK_API_KEY")),
        "env_openai_key": bool(_os.environ.get("OPENAI_API_KEY")),
        "env_openai_base": _os.environ.get("OPENAI_BASE_URL", "<unset>"),
    }
    _run_logger.info(
        "[sentiment-ai] LLM 配置 provider=%s model=%s base=%s key_prefix=%s",
        _cfg.provider, _cfg.model, _cfg.base_url, _dbg["key_prefix"],
    )

    if not is_llm_available():
        _run_logger.warning("[sentiment-ai] LLM 不可用 (api_key 为空且非 ollama)")
        return {"ok": False, "error": "LLM 未配置", "debug": _dbg}

    try:
        step = int(step_raw)
    except (TypeError, ValueError):
        _run_logger.warning("[sentiment-ai] step 参数非法: %r", step_raw)
        return {"ok": False, "error": f"step 必须为整数 1-4，收到 {step_raw!r}"}

    if step not in _SENT_STEP_PROMPTS:
        _run_logger.warning("[sentiment-ai] step 超范围: %s", step)
        return {"ok": False, "error": f"step 必须为 1-4，收到 {step}"}

    system_prompt = _SENT_STEP_PROMPTS[step]
    user_prompt = _build_sentiment_user_prompt(step, header, candidates)
    _run_logger.info(
        "[sentiment-ai] 调用 LLM step=%d sys_prompt_len=%d user_prompt_len=%d",
        step, len(system_prompt), len(user_prompt),
    )

    try:
        client = get_llm_client()
        result = client.chat_json(system_prompt, user_prompt, temperature=0.1)
        phase = str(result.get("phase", ""))
        analysis = str(result.get("analysis", ""))
        suggestion = str(result.get("suggestion", ""))
        _run_logger.info(
            "[sentiment-ai] LLM 成功 step=%d phase=%s analysis_len=%d suggestion_len=%d",
            step, phase, len(analysis), len(suggestion),
        )
        return {
            "ok": True,
            "step": step,
            "phase": phase,
            "analysis": analysis,
            "suggestion": suggestion,
        }
    except Exception as e:
        _run_logger.error("[sentiment-ai] LLM 调用失败 step=%s 错误=%s", step, e, exc_info=True)
        return {"ok": False, "error": f"LLM 调用失败：{e}", "debug": _dbg}


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

    # map frontend tab names to state file names
    _portfolio_file = {
        "v1": "paper_trading_state.json",
        "trend": "paper_trading_state_trend.json",
        "v5": "paper_trading_state_trend.json",
        "ict": "paper_trading_state_ict.json",
    }
    state_file = _portfolio_file.get(portfolio, "paper_trading_state_trend.json")
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
# Daily Review (每日复盘看板) — 移植自 Vibe-Research market.py / gstock.py
# 数据源：腾讯 gtimg（指数，不封IP）+ 东财 push2/push2ex（em_get 内置限流）
# ---------------------------------------------------------------------------

_review_cache: dict = {}
_REVIEW_TTL = 300  # 5 分钟；数据源为空的结果不缓存，下次请求直接重试


def _review_cached(key: str, fn, valid=bool):
    now = time.time()
    hit = _review_cache.get(key)
    if hit and now - hit[0] < _REVIEW_TTL:
        return hit[1]
    val = fn()
    if valid(val):
        _review_cache[key] = (now, val)
    return val


def _em_num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


_A_INDEX_CODES = ["sh000001", "sz399001", "sz399006", "sh000300"]  # 上证/深成/创业板/沪深300


@router.get("/market/indices")
def get_market_indices() -> list[dict]:
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300），腾讯源。"""
    from data.tencent_quotes import fetch_quotes

    quotes = fetch_quotes(_A_INDEX_CODES)
    out = []
    for full in _A_INDEX_CODES:
        q = quotes.get(full)
        if q:
            out.append({"name": q["name"], "price": q["price"], "change_pct": q["change_pct"]})
    return out


_GLOBAL_INDICES = (
    {"key": "dji", "name": "道琼斯", "secid": "100.DJIA", "region": "美股"},
    {"key": "spx", "name": "标普500", "secid": "100.SPX", "region": "美股"},
    {"key": "ndx", "name": "纳斯达克", "secid": "100.NDX", "region": "美股"},
    {"key": "hsi", "name": "恒生指数", "secid": "100.HSI", "region": "港股"},
    {"key": "hstech", "name": "恒生科技", "secid": "124.HSTECH", "region": "港股"},
)


def _push2_stock_get(secid: str, fields: str) -> dict | None:
    """东财 push2 stock/get：push2 优先、失败降级 push2delay（延时行情，看板场景足够）。"""
    from data.eastmoney import em_get

    headers = {"User-Agent": "Mozilla/5.0"}
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/stock/get",
                       params={"secid": secid, "fields": fields},
                       headers=headers, timeout=10)
            d = r.json().get("data")
        except Exception:
            continue
        if d:
            return d
    return None


def _em_price(d: dict, key: str):
    """f43 等价格字段：除以 10^f59 还原。'-'/None → None。"""
    v = d.get(key)
    if not isinstance(v, (int, float)):
        return None
    dec = d.get("f59")
    if not isinstance(dec, int):
        dec = 2
    return round(v / (10 ** dec), dec)


@router.get("/market/global-indices")
def get_global_indices() -> list[dict]:
    """全球指数快照（道指/标普500/纳指/恒生/恒生科技），5 分钟缓存。"""
    def build():
        out = []
        for idx in _GLOBAL_INDICES:
            d = _push2_stock_get(idx["secid"], "f43,f57,f58,f59,f60,f170")
            if not d:
                continue
            chg = d.get("f170")
            out.append({
                "key": idx["key"], "name": idx["name"], "region": idx["region"],
                "price": _em_price(d, "f43"),
                "change_pct": round(chg / 100, 2) if isinstance(chg, (int, float)) else None,
            })
        return out
    return _review_cached("global_indices", build, valid=bool)


_EM_ZT_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _em_zt_pool(endpoint: str, date_str: str, sort: str = "fbt:asc") -> list[dict]:
    """东财涨停板行情中心原始池（push2ex）。
    endpoint: getTopicZTPool(涨停) / getTopicZBPool(炸板) / getTopicDTPool(跌停) / getYesterdayZTPool(昨涨停)
    date: YYYYMMDD 交易日；非交易日/参数错 → []。"""
    from data.eastmoney import em_get

    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": _EM_ZT_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date_str}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception:
        return []


def _em_f(v):
    """东财数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    return v if isinstance(v, (int, float)) else None


@router.get("/market/emotion")
def get_short_term_emotion() -> dict:
    """短线情绪（聚合口径）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单。
    数据源＝东财涨停板四池（push2ex）。"""
    def build():
        # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）
        from collections import Counter

        today = datetime.now().date()
        resolved, zt = "", []
        for back in range(8):
            d = (today - timedelta(days=back)).strftime("%Y%m%d")
            zt = _em_zt_pool("getTopicZTPool", d, "fbt:asc")
            if zt:
                resolved = d
                break
        if not resolved:
            return {}

        zb = _em_zt_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
        dt = _em_zt_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
        yzt = _em_zt_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

        boards = [_em_num(p.get("lbc")) or 1 for p in zt]          # 每只连板数（缺省按 1 板）
        lianban = [b for b in boards if b >= 2]                    # 2 板及以上（连板）
        # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上）
        tiers = Counter(min(b, 5) for b in lianban)
        ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

        # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）
        lianban_stocks = sorted(
            ({
                "code": str(p.get("c", "")), "name": p.get("n", ""),
                "boards": _em_num(p.get("lbc")) or 1,
                "price": round((_em_f(p.get("p")) or 0) / 1000, 2),
                "pct": round(_em_f(p.get("zdp")) or 0, 2),
                "amount": _em_f(p.get("amount")),
                "float_cap": _em_f(p.get("ltsz")),
                "industry": p.get("hybk", ""),
            } for p in zt if (_em_num(p.get("lbc")) or 1) >= 2),
            key=lambda x: (-x["boards"], -(x["amount"] or 0)),
        )

        zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
        attempts = zt_count + zb_count                              # 尝试涨停 = 封住 + 炸板
        seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
        break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
        # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
        promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

        return {
            "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
            "zt_count": zt_count, "dt_count": len(dt), "zb_count": zb_count,
            "max_boards": max(boards) if boards else 0,
            "lianban_count": len(lianban), "ladder": ladder,
            "lianban_stocks": lianban_stocks,
            "seal_rate": seal_rate, "break_rate": break_rate,
            "promotion_rate": promotion_rate, "yzt_count": yzt_count,
        }
    return _review_cached("emotion", build)



_EM_ALL_A = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"  # 沪深京 A 股


def _em_clist(fs: str, fields: str, fid: str = "f3", pz: int = 20, po: int = 1) -> list[dict]:
    """东财行情中心 clist：push2 优先、失败降级 push2delay。"""
    from data.eastmoney import em_get

    params = {"pn": 1, "pz": pz, "po": po, "np": 1, "fltt": 2, "invt": 2,
              "fid": fid, "fs": fs, "fields": fields}
    headers = {"User-Agent": "Mozilla/5.0"}
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers=headers, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            if diff:
                return diff
        except Exception:
            continue
    return []


def _em_sectors() -> list[dict]:
    """行业资金流（按主力净流入降序）。东财行业板块 clist。"""
    diff = _em_clist("m:90 t:2", "f12,f14,f3,f62,f104,f135,f136", fid="f62", pz=90)
    out = []
    for d in diff:
        net = _em_f(d.get("f62"))
        inflow = _em_f(d.get("f135"))
        outflow = _em_f(d.get("f136"))
        out.append({
            "name": d.get("f14", ""),
            "pct": round(_em_f(d.get("f3")) or 0, 2),
            "net": round(net / 1e8, 2) if net is not None else None,
            "inflow": round(inflow / 1e8, 2) if inflow is not None else None,
            "outflow": round(outflow / 1e8, 2) if outflow is not None else None,
            "firms": _em_num(d.get("f104")),
        })
    return [s for s in out if s["name"]]


def _em_sentiment() -> dict:
    """市场情绪：涨跌家数（复用腾讯全市场实时统计，30s 缓存）+ 涨停/跌停（东财四池）+ 宽度/投机度机械分档。"""
    try:
        realtime = get_market_realtime()
    except HTTPException:
        return {}
    up, down, flat = realtime.get("up", 0), realtime.get("down", 0), realtime.get("flat", 0)

    today = datetime.now().strftime("%Y%m%d")
    zt_pool = _em_zt_pool("getTopicZTPool", today)
    dt_pool = _em_zt_pool("getTopicDTPool", today)

    def _real(pool: list[dict]) -> int:
        # 真实涨停/跌停：剔除 ST 与未开板次新（名称 N/C 开头）
        return sum(1 for p in pool
                   if "ST" not in str(p.get("n", "")).upper()
                   and not str(p.get("n", "")).startswith(("N", "C")))

    zt, zt_real = len(zt_pool), _real(zt_pool)
    dt, dt_real = len(dt_pool), _real(dt_pool)

    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"

    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "breadth": breadth, "speculation": speculation,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }


@router.get("/market/pulse")
def get_market_pulse() -> dict:
    """市场情绪 + 行业资金流 + 全市场成交额榜 TOP20（每日复盘看板聚合），5 分钟缓存。"""
    def build():
        return {
            "sentiment": _em_sentiment(),
            "sectors": _em_sectors(),
            "turnover": {"stocks": _em_turnover_top(20),
                         "updated": datetime.now().strftime("%Y-%m-%d %H:%M")},
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    return _review_cached("pulse", build, valid=lambda v: bool(v.get("sentiment") or v.get("sectors")))


def _em_turnover_top(n: int = 20) -> list[dict]:
    """全市场成交额榜（沪深京 A 股按成交额降序 TopN，客观公开榜单）。"""
    diff = _em_clist(_EM_ALL_A, "f12,f14,f2,f3,f6,f20,f21,f100", fid="f6", pz=n)
    return [{
        "code": str(d.get("f12", "")), "name": d.get("f14", ""),
        "price": _em_f(d.get("f2")), "pct": _em_f(d.get("f3")),
        "amount": _em_f(d.get("f6")), "mcap": _em_f(d.get("f20")),
        "float_cap": _em_f(d.get("f21")), "industry": d.get("f100", "") or "",
    } for d in diff]


@router.get("/market/turnover-top")
def get_turnover_top() -> dict:
    """全市场成交额榜 TOP20（客观公开榜单，5 分钟缓存）。"""
    def build():
        return {
            "stocks": _em_turnover_top(20),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    return _review_cached("turnover_top", build, valid=lambda v: bool(v.get("stocks")))


@router.post("/ai/review")
def ai_review(data: dict) -> dict:
    """AI 每日复盘：喂入当日大盘客观数据摘要，返回 AI 生成的复盘文本（非流式）。"""
    summary = data.get("summary", "")
    if not summary:
        return {"error": "No data summary provided"}
    try:
        # LLM key 在根项目 .env（agent/.env 中 MIMO 为注释），显式加载
        try:
            from dotenv import load_dotenv

            load_dotenv(_PROJECT_ROOT / ".env")
        except ImportError:
            pass

        from analysis.llm_analyzer import call_llm

        prompt = (
            f"以下是今天 A 股大盘的客观数据：\n{summary}\n\n"
            "请用中文做一段当天大盘复盘：整体涨跌、主要指数表现、盘面值得注意的点。"
            "只做客观陈述与多视角分析，不预测涨跌、不推荐任何标的、不构成投资建议。"
        )
        # agent/.env 的 LANGCHAIN_MODEL_NAME（openrouter 配置）会污染 call_llm 的模型选择，
        # 显式指定 MIMO 模型（与根项目 .env 一致）
        report = call_llm(prompt, model="mimo-v2.5-pro")
        return {"report": report}
    except Exception as e:
        detail = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail += " | body=" + str(resp.text[:500])
            except Exception:
                pass
        _log.warning("ai_review failed: %s", detail)
        return {"error": detail}


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
        "fibonacci": "strategies/fibonacci/daily_check.py",
        "trend": "strategies/trend/daily_check_trend.py",
        "ict": "strategies/ict/ict_scan_fast.py",
        "sentiment_leader": "-m strategies.sentiment_leader",
        "sentiment": "-m strategies.sentiment_leader",
        "stops": "-m utils stops",
        "review": "analysis/reports/generate_review.py",
        "review_v5": "analysis/reports/generate_review.py",
    }
    if script not in scripts:
        raise HTTPException(status_code=400, detail=f"Unknown script: {script}")

    task_id = str(uuid.uuid4())[:8]
    cmd = scripts[script]
    output_file = _PAPER_DIR / f"script_output_{task_id}.txt"

    ts_start = datetime.now()

    # 安全处理参数
    if cmd.startswith("-m"):
        args = ["python", cmd]
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


@router.get("/logs")
def get_logs(subdir: str = "", name: str = "", tail: int = 200) -> dict:
    """返回 logs/<subdir>/<name>_YYYYMMDD.log 的内容（默认今天，找不到则取最新同名日志）。

    供前端「运行日志」面板读取情绪选股 / AI分析 的运行日志。
    参数: subdir=stock_selection|ai_analysis, name=sentiment_leader|auction_ai_analysis, tail=行数
    """
    if not subdir or not name:
        raise HTTPException(status_code=400, detail="subdir 和 name 必填")
    log_dir = _PROJECT_ROOT / "logs" / subdir
    if not log_dir.is_dir():
        return {"ok": False, "error": f"未找到日志目录: {subdir}", "lines": [], "path": ""}
    today = datetime.now().strftime("%Y%m%d")
    cand = log_dir / f"{name}_{today}.log"
    if not cand.exists():
        matches = sorted(log_dir.glob(f"{name}_*.log"), reverse=True)
        cand = matches[0] if matches else None
    if not cand or not cand.exists():
        return {"ok": False, "error": "暂无日志", "lines": [], "path": ""}
    try:
        lines = cand.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"读取失败: {e}", "lines": [], "path": str(cand)}
    shown = lines[-tail:] if tail and tail > 0 else lines
    return {"ok": True, "path": str(cand), "lines": shown, "total": len(lines)}


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
            f"SELECT code, auction_vol, auction_price, prev_close FROM auction WHERE date=? AND code IN ({auction_placeholders})",
            [today_date] + search_codes,
        ).fetchall()
        today_map = {r[0]: {"today_vol": r[1], "auction_price": r[2], "prev_close": r[3]} for r in today_rows}

        # 同花顺二级行业（stock_ths_industry 使用带前缀代码）
        def _to_prefixed_ths(c: str) -> str:
            if c.startswith(("sh", "sz", "bj")):
                return c
            if c.startswith("6"):
                return "sh" + c
            if c.startswith(("0", "3")):
                return "sz" + c
            return "bj" + c
        ind_search = list(dict.fromkeys([_to_prefixed_ths(c) for c in code_list] + code_list))
        ip_ph = ",".join("?" * len(ind_search))
        ind_by_prefixed: dict = {}
        ind_by_bare: dict = {}
        try:
            ind_rows = db.execute(
                f"SELECT code, industry_l2 FROM stock_ths_industry WHERE code IN ({ip_ph})",
                ind_search,
            ).fetchall()
            for r in ind_rows:
                if r[1]:
                    ind_by_prefixed[r[0]] = r[1]
                    bare = r[0][2:] if r[0].startswith(("sh", "sz", "bj")) else r[0]
                    ind_by_bare[bare] = r[1]
        except sqlite3.OperationalError:
            pass

        # 同花顺概念（concept_count 使用裸 6 位代码，ths_concepts 为 JSON 数组）
        def _parse_ths_concepts(ths: object) -> list:
            if not ths:
                return []
            if isinstance(ths, (list, tuple)):
                return [str(x) for x in ths if x]
            try:
                obj = json.loads(ths)
                return [str(x) for x in obj if x] if isinstance(obj, (list, tuple)) else []
            except Exception:
                return []
        concepts_by_bare: dict = {}
        try:
            cc_search = list(dict.fromkeys(bare_codes + code_list))
            cc_ph = ",".join("?" * len(cc_search))
            cc_rows = db.execute(
                f"SELECT code, ths_concepts FROM concept_count WHERE code IN ({cc_ph})",
                cc_search,
            ).fetchall()
            for r in cc_rows:
                if r[1]:
                    lst = _parse_ths_concepts(r[1])
                    if lst:
                        concepts_by_bare[r[0]] = lst
        except sqlite3.OperationalError:
            pass

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
            pref = _to_prefixed_ths(code)
            t = today_map.get(bare) or today_map.get(code) or {}
            industry = (ind_by_prefixed.get(code) or ind_by_prefixed.get(pref)
                        or ind_by_bare.get(bare) or ind_by_bare.get(code) or "")
            concepts = concepts_by_bare.get(bare) or concepts_by_bare.get(code) or []
            result[code] = {
                "today_vol": t.get("today_vol", 0),
                "prev_vol": prev_map.get(bare) or prev_map.get(code) or 0,
                "auction_price": t.get("auction_price", 0),
                "prev_volume": prev_vol_map.get(code, 0),
                "prev_close": t.get("prev_close", 0),
                "industry": industry,
                "concepts": concepts,
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
        from analysis.external.news_search import get_stock_news

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
        from analysis.external.iwencai import search as iwencai_search
        results = iwencai_search(q, channel="news", size=10)
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
    """Return the generated review report markdown content.

    When no report exists for the requested date (e.g. weekends /
    non-trading days), falls back to the most recent existing review
    report on or before that date so the page is never blank.
    """
    report_date = date if date else datetime.now().strftime("%Y-%m-%d")
    safe_name = Path(report_date).name
    for report_dir in (_PROJECT_ROOT / "reports" / "output", _PROJECT_ROOT / "reports"):
        if not report_dir.exists():
            continue
        for pattern in (f"{safe_name}.md", f"review_{safe_name}.md", f"{safe_name}_review.md"):
            report_file = report_dir / pattern
            if report_file.exists() and report_file.parent == report_dir:
                return {"content": report_file.read_text(encoding="utf-8"), "date": report_date}
    # fallback: most recent review file on/before requested date
    best_file = None
    best_date = None
    for report_dir in (_PROJECT_ROOT / "reports" / "output", _PROJECT_ROOT / "reports"):
        if not report_dir.exists():
            continue
        for f in report_dir.glob("review_*.md"):
            name = f.name
            if not name.startswith("review_") or not name.endswith(".md"):
                continue
            fd = name[len("review_"):-len(".md")]
            if len(fd) == 10 and fd <= report_date and (best_date is None or fd > best_date):
                best_date, best_file = fd, f
    if best_file is not None:
        return {"content": best_file.read_text(encoding="utf-8"), "date": best_date, "fallback": True}
    return {"content": "", "date": report_date}


# ---------------------------------------------------------------------------
# Review AI (复盘 AI 多源分析：豆包 + DeepSeek + 综合)
# ---------------------------------------------------------------------------

def _norm_compact(s: str) -> str:
    """Normalize a date string to 8-digit compact form (YYYYMMDD)."""
    return "".join(ch for ch in (s or "")) if False else "".join(ch for ch in (s or "") if ch.isdigit())[:8]


def _norm_dashed(s: str) -> str:
    """Normalize a date string to YYYY-MM-DD form."""
    c = _norm_compact(s)
    return f"{c[:4]}-{c[4:6]}-{c[6:8]}" if len(c) == 8 else (s or "")


def _build_review_summary(date_str: str):
    """Build a structured yesterday-market summary text from the local DB.

    Returns (summary_text, normalized_compact_date). Relies on daily_kline
    (compact trade_date) for indices / breadth / limit-up-down / turnover and
    fund_daily (dashed date) for per-stock main-net-flow when available.
    """
    dc = _norm_compact(date_str)
    db = _get_db()
    if not db:
        return "（本地行情数据库不可用）", dc
    try:
        cur = db.cursor()
        # 确认日期存在（daily_kline 用紧凑格式，兼容带杠传入）
        row = cur.execute("SELECT 1 FROM daily_kline WHERE trade_date=? LIMIT 1", (dc,)).fetchone()
        if not row:
            dd = _norm_dashed(date_str)
            row = cur.execute("SELECT 1 FROM daily_kline WHERE trade_date=? LIMIT 1", (dd,)).fetchone()
            if row:
                dc = dd
        prev = cur.execute("SELECT MAX(trade_date) FROM daily_kline WHERE trade_date < ?", (dc,)).fetchone()
        prev_dc = prev[0] if prev and prev[0] else None

        lines = [f"## 交易日：{_norm_dashed(dc)}"]

        # 1) 主要指数
        idx_codes = [("sh000001", "上证指数"), ("sz399001", "深证成指"),
                     ("sz399006", "创业板指"), ("sh000688", "科创50")]
        idx_lines = ["### 主要指数"]
        for code, name in idx_codes:
            r = cur.execute("SELECT close FROM daily_kline WHERE code=? AND trade_date=? LIMIT 1", (code, dc)).fetchone()
            if not r:
                continue
            close = r[0]
            chg = ""
            if prev_dc:
                p = cur.execute("SELECT close FROM daily_kline WHERE code=? AND trade_date=? LIMIT 1", (code, prev_dc)).fetchone()
                if p and p[0]:
                    chg = f"（{(close / p[0] - 1) * 100:+.2f}%）"
            idx_lines.append(f"- {name}：{close}{chg}")
        lines.append("\n".join(idx_lines))

        # 2) 市场宽度 + 涨停/跌停（与上一交易日 self-join）
        if prev_dc:
            b = cur.execute(
                """
                SELECT
                  SUM(CASE WHEN t.close > p.close THEN 1 ELSE 0 END) up,
                  SUM(CASE WHEN t.close < p.close THEN 1 ELSE 0 END) down,
                  SUM(CASE WHEN t.close = p.close THEN 1 ELSE 0 END) flat,
                  SUM(CASE WHEN t.close >= p.close * 1.095 THEN 1 ELSE 0 END) lu,
                  SUM(CASE WHEN t.close <= p.close * 0.905 THEN 1 ELSE 0 END) ld
                FROM daily_kline t
                JOIN daily_kline p ON t.code = p.code AND t.market = p.market
                WHERE t.trade_date = ? AND p.trade_date = ?
                  AND t.code NOT IN ('sh000001','sz399001','sz399006','sh000688')
                """,
                (dc, prev_dc),
            ).fetchone()
            if b:
                up, down, flat, lu, ld = b
                tot = (up or 0) + (down or 0) + (flat or 0)
                lines.append(
                    "### 市场宽度\n"
                    f"- 上涨 {up or 0} 家 / 下跌 {down or 0} 家 / 平盘 {flat or 0} 家（共 {tot} 只）\n"
                    f"- 涨停约 {lu or 0} 只 / 跌停约 {ld or 0} 只"
                )

        # 3) 成交额 TOP10（daily_kline.amount 在本库多为 NULL，仅在可用时输出）
        name_map = {c: n for c, n in cur.execute("SELECT code, name FROM stock_names").fetchall()}
        amount_rows = cur.execute(
            "SELECT COUNT(*) FROM daily_kline WHERE trade_date=? AND amount IS NOT NULL AND amount > 0 "
            "AND code NOT IN ('sh000001','sz399001','sz399006','sh000688')",
            (dc,),
        ).fetchone()[0]
        if amount_rows:
            top = cur.execute(
                "SELECT code, amount, close FROM daily_kline "
                "WHERE trade_date=? AND amount IS NOT NULL AND amount > 0 "
                "AND code NOT IN ('sh000001','sz399001','sz399006','sh000688') "
                "ORDER BY amount DESC LIMIT 10",
                (dc,),
            ).fetchall()
            tl = ["### 成交额 TOP10"]
            for i, (code, amt, close) in enumerate(top, 1):
                nm = name_map.get(code, code)
                amt_yi = (amt or 0) / 1e8
                tl.append(f"{i}. {nm}({code})：成交额 {amt_yi:.1f}亿，收盘 {close}")
            lines.append("\n".join(tl))
        else:
            lines.append("### 成交额\n- （该日 daily_kline 未提供成交额字段，未列出成交额榜）")

        # 4) 主力净流入 TOP10（fund_daily 为带杠日期，且数据可能稀疏）
        dd = _norm_dashed(dc)
        frows = cur.execute(
            "SELECT code, main_net_flow FROM fund_daily WHERE date=? ORDER BY main_net_flow DESC LIMIT 10",
            (dd,),
        ).fetchall()
        if frows:
            fl = ["### 主力净流入 TOP10（个股）"]
            for i, (code, net) in enumerate(frows, 1):
                nm = name_map.get(code, code)
                net_yi = (net or 0) / 1e8
                fl.append(f"{i}. {nm}({code})：主力净流入 {net_yi:+.2f}亿")
            lines.append("\n".join(fl))
        else:
            lines.append("### 主力资金\n- （该日 fund_daily 无数据，未提供个股主力净流入）")
    except Exception as e:
        _log.warning("review summary failed: %s", e)
        lines = [f"（本地数据汇总失败：{e}）"]
    finally:
        db.close()
    return "\n\n".join(lines), dc


# 复盘分析框架 = 提示词合集《六、综合实战版》原文 + 《七、通用增强要求》原文，严格照搬，不自行发挥
_REVIEW_FRAMEWORK = """请对昨日 A 股市场做一份综合行情分析，兼顾指数、情绪、热点、资金、风险和应对思路，要求结构化输出，逻辑清晰，避免空话。

请按以下结构展开：

一、指数与市场结构
- 上证指数、深证成指、创业板指等主要指数表现
- 市场整体是普涨普跌还是结构分化
- 指数强弱与个股赚钱效应是否一致

二、情绪周期
- 当前市场情绪属于修复、分歧、高潮、退潮还是混沌阶段
- 高标股、连板股、核心题材股反馈如何
- 当前短线生态是改善还是恶化

三、热点与主线
- 当前最强的 3 个方向是什么
- 每个方向的催化逻辑、市场认可度、持续性如何
- 是否已经形成主线，还是快速轮动

四、资金风格
- 资金更偏权重、防御、红利、科技成长还是小盘题材
- 资金风格是否稳定
- 市场是增量推动还是存量博弈

五、风险评估
- 当前市场最大的风险点是什么
- 哪些板块或风格最容易出现回撤
- 哪些信号会破坏当前行情结构

六、应对思路
- 当前更适合进攻、控制仓位、等待确认还是偏防守
- 短线和波段投资者分别应关注什么
- 后续最重要的观察变量是什么

七、总结
- 用"市场状态、主线方向、风险提示、后续观察点"做简要总结

要求：
- 每个结论尽量给出依据
- 区分事实、判断、推演
- 不做绝对化预测
- 输出风格偏专业复盘和交易研判

补充要求：
- 不要只复述指数涨跌，要解释市场结构
- 不要只罗列热点名称，要说明热点逻辑与持续性
- 不要只说情绪好或差，要给出判断依据
- 明确区分：事实、判断、推演
- 如果出现数据不确定或无法确认，请直接说明
- 输出尽量偏交易复盘，而不是新闻摘要
- 如果数据不确定，请明确说明；不要自行编造。"""


# 明日预演框架 = 提示词合集《二、盘前版：盘前研判》原文 + 《七、通用增强要求》原文，严格照搬，不自行发挥
_PREVIEW_FRAMEWORK = """请对今日 A 股市场做一份盘前分析，目标是判断今天大盘可能的运行节奏、热点方向和风险点。

请按以下框架输出：

1. 外围与宏观影响
- 隔夜海外市场表现对 A 股可能有哪些影响
- 宏观政策、消息面、行业新闻中，哪些最可能影响今日开盘情绪
- 富时 A50 期货夜盘、纳斯达克中国金龙指数、费城半导体指数 SOX
- 每项给出涨跌幅，并用一句话说明对今日 A 股开盘意味着什么（偏多 / 偏空 / 中性）
- 美股：道指、纳指、标普，以及特斯拉、英伟达、苹果等重点个股，涨跌幅超过 ±2% 的请标注
- 商品与汇率：原油、黄金、铜、美元指数、离岸人民币、美债收益率，并注明各自对应 A 股哪条线
- 美联储表态、地缘政治、海外政策（关税 / 出口管制）、海外大公司事件
- 每条注明重要程度（高 / 中 / 低）和发布时间
- 外围明显利空、但 A50 期货没跟跌 → 请单独指出，这可能是 A 股走独立行情的信号
- 列出本期外围中"看似重要但对 A 股基本无效"的项，并说明原因

2. 大盘预期
- 今日大盘更可能高开、低开还是震荡开盘
- 市场整体偏进攻、偏防守还是偏观望
- 影响今日市场节奏的关键变量是什么

3. 重点方向
- 今日最值得关注的 3 个方向或板块
- 每个方向的逻辑是什么
- 哪些方向只是消息刺激，哪些方向可能具备持续性
- 最有预期差的方向是什么，并说明逻辑

4. 情绪与短线接力
- 今日短线情绪更可能修复、延续、分歧还是退潮
- 昨日连板股、高标股、强势板块是否有参考意义
- 今日短线博弈要重点防什么

5. 风险提示
- 哪些方向可能高开低走
- 哪些板块已经透支预期
- 哪些信号出现后要转为谨慎

6. 盘前结论
- 用简洁语言概括今日市场可能的主基调
- 说明今天更适合观察什么，而不是盲目追什么

要求：
- 明确区分"已知事实"和"盘前推演"
- 不做绝对化预测
- 尽量写出条件判断，而不是单向结论

补充要求：
- 不要只复述指数涨跌，要解释市场结构
- 不要只罗列热点名称，要说明热点逻辑与持续性
- 不要只说情绪好或差，要给出判断依据
- 明确区分：事实、判断、推演
- 如果出现数据不确定或无法确认，请直接说明
- 输出尽量偏交易复盘，而不是新闻摘要
- 如果数据不确定，请明确说明；不要自行编造。"""


def _prev_bizday(dashed: str) -> str:
    """dashed 日期的前一交易日（仅跳过周末，不判断节假日）。"""
    from datetime import date as _d, timedelta as _td

    d = _d(int(dashed[:4]), int(dashed[5:7]), int(dashed[8:10]))
    d -= _td(days=1)
    while d.weekday() >= 5:  # 5=周六 6=周日
        d -= _td(days=1)
    return d.strftime("%Y-%m-%d")


@router.get("/review/preview-prompt")
def review_preview_prompt(date: str = "") -> dict:
    """返回发给豆包/DeepSeek 的今日预演 prompt（盘前研判当日）。

    date = 研判对象日（盘前触发传当天）；基础数据日 = 其前一交易日。
    用户要求：只发「提示词合集」第二节（盘前版）+ 第七节（通用增强要求）的**原文**，
    不附加本地数据（本地数据仅由后端 /review/preview-analysis 在综合阶段用于交叉验证）。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    dd = _norm_dashed(date)
    pd_ = _prev_bizday(dd)
    # 框架原文以「今日」指代研判对象、「昨日」指代前一交易日，需锚定具体日期避免歧义
    prompt = (
        f"（本次盘前研判对象为 {dd}，即 {pd_}（前一交易日）之后的交易日；"
        f"下文「今日」均指 {dd}，「昨日」均指 {pd_}。）\n\n{_PREVIEW_FRAMEWORK}"
    )
    return {"prompt": prompt, "date": dd, "prev_bizday": pd_}


@router.get("/review/report")
def review_report(date: str = "", kind: str = "preview") -> dict:
    """读取已导出的 AI 复盘/预演 md 文件内容（reports/output/ai_review/{date}_{kind}.md）。

    kind: "preview"(今日预演) | "review"(昨日复盘)。文件不存在返回 exists=False。
    前端以此为当日结果的权威来源：有文件直接回显，避免每次重跑分析。
    """
    if kind not in ("preview", "review"):
        kind = "preview"
    dd = _norm_dashed(date) if date else datetime.now().strftime("%Y-%m-%d")
    path = _PROJECT_ROOT / "reports" / "output" / "ai_review" / f"{dd}_{kind}.md"
    if not path.exists():
        return {"exists": False, "date": dd, "kind": kind}
    try:
        content = path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return {"exists": False, "date": dd, "kind": kind}
    return {"exists": True, "date": dd, "kind": kind, "content": content, "mtime": mtime}


@router.get("/review/ai-prompt")
def review_ai_prompt(date: str = "") -> dict:
    """返回发给豆包/DeepSeek 的昨日复盘 prompt。

    用户要求：只发「提示词合集」第六节（综合实战版）+ 第七节（通用增强要求）的**原文**，
    不附加本地数据摘要（本地数据仅由后端 /review/ai-analysis 在综合阶段用于交叉验证）。
    因此这里不再调用 _build_review_summary（该查询约 9s），接口可即时返回。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    dd = _norm_dashed(date)
    # 框架原文以「昨日」指代复盘对象；按钮已改为盘后分析当天，需一行日期锚定避免差一天
    prompt = f"（本次复盘交易日为 {dd}，下文「昨日」均指 {dd}。）\n\n{_REVIEW_FRAMEWORK}"
    return {"prompt": prompt, "date": dd, "summary": ""}


def _extract_conclusion(report: str) -> str:
    """从 MiMo 综合结果中提取浓缩结论（「【最终结论】」标记之后到文末），无则返回空串。"""
    if not report:
        return ""
    marker = "【最终结论】"
    idx = report.rfind(marker)
    if idx < 0:
        return ""
    seg = report[idx + len(marker):].strip().lstrip("：:。 ")
    return seg[:2000]


def _save_ai_report(
    kind: str, date: str, report: str, sources: list[tuple[str, str]] | None = None
) -> str:
    """把 AI 复盘/预演导出为 md：含豆包/DeepSeek 各来源原始回答 + 项目 LLM 综合结论。

    kind: "review"(复盘) | "preview"(预演)
    sources: [(label, answer), ...] 各路 LLM 原始回答；report: MiMo 综合结论。
    返回文件路径；写入失败返回空串。原子写入（tmp+replace）。
    """
    if not report:
        return ""
    out = _PROJECT_ROOT / "reports" / "output" / "ai_review"
    try:
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{date}_{kind}.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = "AI 多源复盘" if kind == "review" else "AI 今日预演"
        lines = [f"# {title}（{date}）", "", f"> 生成于 {now}", ""]
        if sources:
            lines += ["## 各来源原始回答", ""]
            for label, ans in sources:
                lines += [f"### {label}", "", ans.strip(), ""]
        lines += ["---", "", f"## {title}综合结论（项目 LLM）", "", report.strip(), ""]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        tmp.replace(path)
        return str(path)
    except Exception as exc:  # noqa: BLE001
        _log.warning("保存 AI%s(%s) 失败：%s", kind, date, str(exc)[:200])
        return ""


@router.post("/review/ai-analysis")
def review_ai_analysis(data: dict) -> dict:
    """复盘多源 AI 分析：综合豆包+DeepSeek 的回答，结合本地数据交叉验证输出最终复盘。

    Body: { "date": "YYYY-MM-DD", "web_answers": [{target,label,answer}...] }
    项目 LLM 只综合 web_answers，不自己独立分析；无回答时返回 error 提示先获取/粘贴。
    """
    # 与本项目其他 LLM 调用保持一致：函数内局部导入，并显式加载根项目 .env。
    # （agent/.env 里的 LANGCHAIN_MODEL_NAME 等 openrouter 配置会污染 call_llm 的模型/密钥选择）
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    from analysis.llm_analyzer import call_llm

    date_str = data.get("date", "") or datetime.now().strftime("%Y-%m-%d")
    dd = _norm_dashed(date_str)

    web_answers = data.get("web_answers") or []
    blocks = []
    labels: list[str] = []
    src_pairs: list[tuple[str, str]] = []
    for w in web_answers:
        if not isinstance(w, dict):
            continue
        label = (w.get("label") or w.get("target") or "AI")
        ans = (w.get("answer") or "").strip()
        if ans:
            blocks.append(f"### {label} 的回答\n{ans[:3000]}")
            labels.append(label)
            src_pairs.append((label, ans[:3000]))

    if not blocks:
        # 项目 LLM 只综合豆包/DeepSeek 的回答，不自己独立分析本地数据
        return {
            "report": "",
            "error": "没有可综合的回答：请先一键发送或手动粘贴豆包/DeepSeek 的回答，再做多源综合复盘",
            "date": dd,
            "synthesized": False,
        }

    summary, _dc = _build_review_summary(dd)

    if blocks:
        # 来源数量按实际传入动态生成：若某路（如豆包）失败只剩一路，
        # 写死「豆包与 DeepSeek 两个模型」会让 LLM 凭空编造未提供的那一方的观点。
        src_desc = "、".join(labels)
        synth_sys = (
            f"你是 A 股复盘多源分析师。任务：综合 {src_desc} 对昨日 A 股的复盘分析，"
            "结合下方本地客观数据交叉验证，输出最终复盘。\n"
            "要求：\n"
            f"1. 观点对比：提炼各家核心判断（实际来源共 {len(labels)} 个：{src_desc}），指出方向一致处与分歧点\n"
            "2. 数据验证：哪些观点与本地数据（指数涨跌/市场宽度/涨停跌停/成交额/主力资金）吻合，哪些缺乏支持\n"
            "3. 按【指数与市场结构 / 情绪周期 / 热点与主线 / 资金风格 / 风险评估 / 应对思路 / 总结】七段输出最终复盘\n"
            "4. 结论明确，拒绝和稀泥；区分事实、判断、推演；禁止编造数字。\n"
            f"5. 严格限制：只依据下方实际给出的 {len(labels)} 个来源作答；"
            "若只有一个来源，就如实说明「仅单一来源，缺少交叉验证」，"
            "**严禁虚构任何未提供来源的名称或观点**。\n"
            f"6. 最后单独以一行「【最终结论】」开头，按上面各段（指数与市场结构/情绪周期/热点与主线/资金风格/风险评估/应对思路/总结）**逐维度写出详细结论**，"
            "每个维度 2~4 句（明确的判断 + 核心理由 + 关键数据支撑），并对比 {src_desc} 各来源在该维度上观点的一致处与分歧点、给出你的裁决依据；"
            "用「1. 2. 3. …」分条列出。复盘时间充裕，结论要求完整详实、可独立成文，**不要**压缩成一句话或省略论证。"
        )
        synth_prompt = (
            f"### 本地客观数据（{dd}）\n{summary[:5000]}\n\n"
            + "\n\n".join(blocks)
            + "\n\n请按上述要求输出多源综合最终复盘。"
        )
        try:
            synthesis = call_llm(synth_prompt, model="mimo-v2.5-pro", system_prompt=synth_sys)
        except Exception as exc:  # noqa: BLE001
            _log.warning("review synthesis failed: %s", str(exc)[:200])
            synthesis = f"（LLM 综合失败：{str(exc)[:200]}）"
        _save_ai_report("review", dd, synthesis, src_pairs or None)
        return {"report": synthesis, "conclusion": _extract_conclusion(synthesis), "date": dd, "sources": len(blocks), "synthesized": True}


@router.post("/review/preview-analysis")
def review_preview_analysis(data: dict) -> dict:
    """今日预演多源 AI 分析：综合豆包+DeepSeek 的回答，结合前一交易日本地收盘数据输出当日预演。

    Body: { "date": "YYYY-MM-DD", "web_answers": [{target,label,answer}...] }
    date = 研判对象日（盘前触发传当天）；web_answers 非空时做多源综合；
    为空时退化为仅本地数据的 AI 预演。
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    from analysis.llm_analyzer import call_llm

    date_str = data.get("date", "") or datetime.now().strftime("%Y-%m-%d")
    target = _norm_dashed(date_str)  # 研判对象日（今日）
    base = _prev_bizday(target)  # 基础数据日（前一交易日）
    summary, dc = _build_review_summary(base)
    logs: list[str] = []
    logs.append(f"本地数据摘要就绪（base={dc} · summary={len(summary)} 字符）")

    web_answers = data.get("web_answers") or []
    blocks = []
    labels: list[str] = []
    src_pairs: list[tuple[str, str]] = []
    for w in web_answers:
        if not isinstance(w, dict):
            continue
        label = (w.get("label") or w.get("target") or "AI")
        ans = (w.get("answer") or "").strip()
        if ans:
            blocks.append(f"### {label} 的回答\n{ans[:3000]}")
            labels.append(label)
            src_pairs.append((label, ans[:3000]))
    logs.append(f"收到 {len(blocks)} 路外部回答：{('、'.join(labels) or '无')}")

    if blocks:
        # 来源数量按实际传入动态生成，严禁让 LLM 虚构未提供的来源观点
        src_desc = "、".join(labels)
        synth_sys = (
            f"你是 A 股盘前研判多源分析师。任务：综合 {src_desc} 对 {target}（今日）的盘前研判，"
            f"结合 {dc}（前一交易日）本地收盘数据交叉验证，输出对 {target} 的最终预演。\n"
            "要求：\n"
            f"1. 观点对比：提炼各家核心判断（实际来源共 {len(labels)} 个：{src_desc}），指出方向一致处与分歧点\n"
            "2. 数据验证：哪些观点与前一交易日本地数据（指数涨跌/市场宽度/涨停跌停/成交额/主力资金）吻合，哪些缺乏支持\n"
             "3. 按【外围与宏观影响 / 大盘预期 / 重点方向 / 情绪与短线接力 / 风险提示 / 盘前结论】六段输出最终预演\n"
            "4. 结论明确，拒绝和稀泥；区分事实、判断、推演；禁止编造数字。\n"
            f"5. 严格限制：只依据下方实际给出的 {len(labels)} 个来源作答；"
            "若只有一个来源，就如实说明「仅单一来源，缺少交叉验证」，"
            "**严禁虚构任何未提供来源的名称或观点**。\n"
            "6. 最后单独以一行「【最终结论】」开头，把上面各段（外围与宏观影响/大盘预期/重点方向/情绪与短线接力/风险提示/盘前结论）的结论**每个维度各提炼一条**，"
            "用「1. 2. 3. …」分条列出——每条覆盖一个维度，给出明确的判断和核心理由，保留各维度自己的结论（忽略完整分析的长篇论证与数据罗列）。"
        )
        synth_prompt = (
            f"### 前一交易日本地客观数据（{dc}）\n{summary[:5000]}\n\n"
            + "\n\n".join(blocks)
            + "\n\n请按上述要求输出多源综合最终预演。"
        )
        try:
            synthesis = call_llm(synth_prompt, model="mimo-v2.5-pro", system_prompt=synth_sys, timeout=180, log=logs.append)
        except Exception as exc:  # noqa: BLE001
            _log.warning("preview synthesis failed: %s", str(exc)[:200])
            synthesis = f"（LLM 综合失败：{str(exc)[:200]}）"
            logs.append(f"综合调用异常：{str(exc)[:200]}")
        _save_ai_report("preview", target, synthesis, src_pairs or None)
        logs.append(f"综合完成（{len(synthesis)} 字），md 已落盘 reports/output/ai_review/{target}_preview.md")
        return {"report": synthesis, "conclusion": _extract_conclusion(synthesis), "date": target, "base_date": dc, "sources": len(blocks), "synthesized": True, "logs": logs}

    # 退化：仅本地数据 AI 预演
    logs.append("无外部回答，退化为仅本地数据 AI 预演")
    base_sys = "你是 A 股盘前研判分析师，基于前一交易日收盘客观数据预判当日，结论明确、区分事实与推演、禁止编造数字。"
    base_prompt = (
        f"以下是 {dc}（前一交易日）A股本地收盘数据，请预判 {target}（今日），"
        f"按【外围与宏观影响/大盘预期/重点方向/情绪与短线接力/风险提示/盘前结论】六段输出预演：\n\n{summary[:5000]}"
    )
    try:
        report = call_llm(base_prompt, model="mimo-v2.5-pro", system_prompt=base_sys, timeout=180, log=logs.append)
    except Exception as exc:  # noqa: BLE001
        _log.warning("preview base analysis failed: %s", str(exc)[:200])
        report = f"（AI 预演生成失败：{str(exc)[:200]}）"
        logs.append(f"AI 预演调用异常：{str(exc)[:200]}")
    _save_ai_report("preview", target, report)
    return {"report": report, "conclusion": _extract_conclusion(report), "date": target, "base_date": dc, "sources": 0, "synthesized": False, "logs": logs}


def _read_vibe_review(date_str: str) -> dict:
    """读取 ~/.duanxian-agents/reviews/{date}.json 当日复盘结论。"""
    review = Path.home() / ".duanxian-agents" / "reviews" / f"{_norm_dashed(date_str)}.json"
    try:
        return json.loads(review.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _build_verify_context(target: str):
    """组装盘后验证上下文：早晨预演（今日盘前 AI 预演）+ 今日收盘实况。

    返回 (prompt 上下文文本, 结构 dict)。早晨预演来源：
    ① reports/output/ai_review/{target}_preview.md（盘前 AI 预演六段）
    ② 退化：vibe 复盘结论中的明日关注点+验证条件（自体面交代数据缺失）
    """
    preview_path = _PROJECT_ROOT / "reports" / "output" / "ai_review" / f"{target}_preview.md"
    preview_text = ""
    try:
        if preview_path.exists() and preview_path.stat().st_size > 0:
            preview_text = preview_path.read_text(encoding="utf-8")
    except OSError:
        pass

    summary, _dc = _build_review_summary(target)

    if preview_text:
        blocks = [f"## 今日（{target}）早晨预演（盘前 AI 预演）\n{preview_text[:6000]}"]
        ctx = {
            "date": _norm_dashed(target),
            "prev_date": _norm_dashed(_prev_bizday(target)),
            "phase": "",
            "directions": [],
            "verification_items": [],
            "oneliner": "",
            "source": "preview",
        }
    else:
        # 退化：无今日预演，回退读昨日 vibe 复盘结论（明日关注点）
        prev = _prev_bizday(target)
        review = _read_vibe_review(prev)
        focus = review.get("focus") or {}
        directions = focus.get("focus_directions") or []
        vitems = focus.get("verification_items") or []
        phase = focus.get("emotion_phase", "")
        oneliner = focus.get("market_oneliner", "")
        blocks = [f"## 昨日（{_norm_dashed(prev)}）复盘结论（无今日预演，退化来源）"]
        blocks.append(f"- 情绪档位：{phase or '未知'}\n- 一句话判断：{oneliner or '（无）'}")
        if directions:
            d_lines = ["### 明日关注方向（昨日给出）"]
            for i, d in enumerate(directions, 1):
                d_lines.append(f"{i}. {d.get('direction','')}：{d.get('logic','')}（风险：{d.get('risk','')}）")
            blocks.append("\n".join(d_lines))
        else:
            blocks.append("- 昨日未给明日方向")
        if vitems:
            v_lines = ["### 明日验证条件（昨日给出，待今日核验）"]
            for i, v in enumerate(vitems, 1):
                v_lines.append(f"{i}. {v.get('metric','')} 预期「{v.get('direction','')}」——{v.get('reason','')}")
            blocks.append("\n".join(v_lines))
        else:
            blocks.append("- 昨日未给验证条件")
        ctx = {
            "date": _norm_dashed(target),
            "prev_date": _norm_dashed(prev),
            "phase": phase,
            "directions": directions,
            "verification_items": vitems,
            "oneliner": oneliner,
            "source": "vibe_fallback",
        }

    blocks.append(f"\n## 今日（{_norm_dashed(target)}）收盘实况\n{summary}")
    return "\n\n".join(blocks), ctx


_VERIFY_FRAMEWORK = """你是一名 A 股盘后验证分析师。任务：用【今日收盘实况】逐条核验【今日早晨预演（盘前 AI 预演）】给出的六段预判，输出一份"早晨预判兑现了吗"的核验报告。

要求：
1. 逐条判定：从早晨预演中提炼各维度核心判断（大盘方向、重点方向、情绪节奏、风险点等），结合今日收盘数据逐一评分。
2. 判定口径：每个维度判「兑现 / 部分兑现 / 未兑现 / 数据不足」，并给出数据依据。
3. 数据说话：引用今日具体的指数涨跌、涨停跌停、连板、封板/炸板率、成交额、资金流读数来支撑判定。数据缺失或不足以判定的，如实说明，禁止编造。
4. 输出结构：
   - 一、结论总览：早晨预演总体兑现情况（兑现 / 部分兑现 / 证伪 / 无法判断），一句话总结
   - 二、逐维度核验：按预演六段分别核验（含评分与依据）
   - 三、含金量评估：对早晨预演质量做一个复盘式点评
   - 四、修正意见：若判断有误，明日应如何修正，明日关注什么
5. 结论明确，拒绝和稀泥；区分事实、判断、推演；禁止编造数字。"""


@router.get("/review/verify-prompt")
def review_verify_prompt(date: str = "") -> dict:
    """返回发给豆包/DeepSeek 的盘后验证 prompt（早晨预演 vs 今日收盘核验）。

    date = 待验证的交易日本身（盘后触发传当天）。早晨预演取
    reports/output/ai_review/{date}_preview.md（盘前 AI 预演完整 md）；
    若无预演文件则回退 vibe 复盘结论。
今日收盘实况由 verify-analysis 综合阶段用于交叉验证，故 prompt 只发预判骨架，
    不在接口内拼接重量级本地数据（保持即时返回）。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    dd = _norm_dashed(date)
    preview_path = _PROJECT_ROOT / "reports" / "output" / "ai_review" / f"{dd}_preview.md"
    preview_text = ""
    try:
        if preview_path.exists() and preview_path.stat().st_size > 0:
            preview_text = preview_path.read_text(encoding="utf-8")
    except OSError:
        pass

    lines = [f"（本次盘后验证对象：{dd}，下文「今日」均指 {dd}。）", _VERIFY_FRAMEWORK]
    if preview_text:
        lines.append(f"\n## 今日（{dd}）早晨预演（盘前 AI 预演）\n{preview_text[:5000]}")
    else:
        prev = _prev_bizday(dd)
        review = _read_vibe_review(prev)
        focus = review.get("focus") or {}
        directions = focus.get("focus_directions") or []
        vitems = focus.get("verification_items") or []
        lines.append(
            f"\n## 昨日（{prev}）给出的预判（无今日预演时的退化来源）\n"
            f"- 情绪档位：{focus.get('emotion_phase','未知')}"
        )
        if directions:
            lines.append("\n### 明日方向")
            for i, d in enumerate(directions, 1):
                lines.append(f"{i}. {d.get('direction','')}：{d.get('logic','')}")
        if vitems:
            lines.append("\n### 明日验证条件（今日待核验）")
            for i, v in enumerate(vitems, 1):
                lines.append(f"{i}. {v.get('metric','')} 预期「{v.get('direction','')}」——{v.get('reason','')}")
    return {"prompt": "\n\n".join(lines), "date": dd, "prev_date": dd, "summary": ""}


def _save_verify_narrative(report: str, ctx: dict) -> None:
    """把 MiMo 盘后验证结论写进 vibe reflection（prediction_date=昨日）。

    reflection 由 vibe 次日回评自动生成 keyed by prediction_date；这里合并写入一个
    llm_narrative 字段，与结构化 per-item 核验并存，随次日复盘展示。文件不存在则创建。
    """
    import uuid as _uuid

    pred = ctx.get("prev_date") or ""
    eval_date = ctx.get("date") or ""
    if not pred or not report:
        return
    refl_dir = Path.home() / ".duanxian-agents" / "reflections"
    path = refl_dir / f"{pred}.json"
    env: dict = {}
    try:
        if path.is_file():
            env = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 坏文件则重建
        env = {}
    env["llm_narrative"] = {
        "eval_date": eval_date,
        "prev_date": pred,
        "report": report,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "phase": ctx.get("phase", ""),
        "directions": ctx.get("directions", []),
        "verification_items": ctx.get("verification_items", []),
        "oneliner": ctx.get("oneliner", ""),
    }
    try:
        refl_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{_uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        _log.warning("保存验证 narrative 失败(%s)：%s", pred, str(exc)[:200])


@router.post("/review/verify-analysis")
def review_verify_analysis(data: dict) -> dict:
    """盘后验证多源 AI 分析：综合豆包+DeepSeek 的回答，结合今日收盘数据输出核验结论。

    Body: { "date": "YYYY-MM-DD", "web_answers": [{target,label,answer}...] }
    web_answers 非空做多源综合；为空退化为仅本地数据的验证。
    结论落盘到 vibe reflection（~/.duanxian-agents/reflections/{prev_date}.json）的 llm_narrative 字段，
    与结构化 per-item 核验并存，随次日复盘自动展示。
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        pass

    from analysis.llm_analyzer import call_llm

    date_str = data.get("date", "") or datetime.now().strftime("%Y-%m-%d")
    target = _norm_dashed(date_str)
    context, ctx = _build_verify_context(target)

    web_answers = data.get("web_answers") or []
    blocks = []
    labels: list[str] = []
    for w in web_answers:
        if not isinstance(w, dict):
            continue
        label = (w.get("label") or w.get("target") or "AI")
        ans = (w.get("answer") or "").strip()
        if ans:
            blocks.append(f"### {label} 的回答\n{ans[:3000]}")
            labels.append(label)

    if blocks:
        src_desc = "、".join(labels)
        synth_sys = (
            f"你是 A 股盘后验证多源分析师。任务：综合 {src_desc} 对今日核验的判断，"
            "结合下方本地收盘数据交叉验证，输出最终核验报告。\n"
            "要求：\n"
            f"1. 观点对比：提炼各家核验结论（实际来源共 {len(labels)} 个：{src_desc}），指出一致处与分歧点\n"
            "2. 数据验证：哪些核验与本地数据（指数/宽度/涨停跌停/成交额/资金流）吻合，哪些缺乏支持\n"
            "3. 按【方向核验 / 条件核验 / 含金量评估 / 修正意见 / 总结】五段输出最终核验报告\n"
            "4. 结论明确，拒绝和稀泥；区分事实、判断、推演；禁止编造数字。\n"
            f"5. 严格限制：只依据下方实际给出的 {len(labels)} 个来源作答；"
            "若只有一个来源，就如实说明「仅单一来源，缺少交叉验证」，"
            "**严禁虚构任何未提供来源的名称或观点**。"
        )
        synth_prompt = f"### 本次待核验预判与今日收盘实况\n{context[:6000]}\n\n" + "\n\n".join(blocks) + "\n\n请按上述要求输出多源综合最终核验报告。"
        try:
            synthesis = call_llm(synth_prompt, model="mimo-v2.5-pro", system_prompt=synth_sys)
        except Exception as exc:  # noqa: BLE001
            _log.warning("verify synthesis failed: %s", str(exc)[:200])
            synthesis = f"（LLM 综合失败：{str(exc)[:200]}）"
        _save_verify_narrative(synthesis, ctx)
        return {"report": synthesis, "date": target, "sources": len(blocks), "synthesized": True, **ctx}

    # 退化：仅本地数据盘后验证
    try:
        report = call_llm(
            f"{_VERIFY_FRAMEWORK}\n\n以下为待核验上下文与今日收盘实况：\n\n{context[:7000]}",
            model="mimo-v2.5-pro",
            system_prompt="你是 A 股盘后验证分析师，基于本地客观数据逐条核验昨日预判，结论明确、区分事实与推演、禁止编造数字。",
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("verify base analysis failed: %s", str(exc)[:200])
        report = f"（盘后验证生成失败：{str(exc)[:200]}）"
    _save_verify_narrative(report, ctx)
    return {"report": report, "date": target, "sources": 0, "synthesized": False, **ctx}


# ---------------------------------------------------------------------------
# Auction Board (集合竞价看板)
# ---------------------------------------------------------------------------

def _import_auction_excel(db, date_str: str) -> int:
    """Import auction data from Excel file in project root.

    Looks for 竞价数据_YYYY-MM-DD.xlsx, imports into auction table.
    Returns number of rows imported, or 0 if no file / import failed.
    """
    xlsx = _PROJECT_ROOT / f'竞价数据_{date_str}.xlsx'
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
            vol = int(row.get('竞价量(手)', 0))  # 单位=手（与DB一致）
            amount = float(row.get('竞价额(万元)', 0))  # 单位=万元（与DB一致）
            open_px = float(row.get('开盘价', 0))
            prev_close = float(row.get('昨收', 0))
            collect_time = str(row.get('采集时间', ''))
            # Excel没有竞价价列，用开盘价近似
            price = open_px
            cur.execute(
                "INSERT OR REPLACE INTO auction (date, code, name, auction_vol, auction_amount, auction_price, open_price, collect_time, prev_close) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (date_str, code, name, vol, amount, price, open_px, collect_time, prev_close)
            )
            imported += 1
        db.commit()
        _log.info("imported %d auction rows from %s", imported, xlsx.name)
        return imported
    except Exception as ex:
        _log.warning("auction Excel import failed: %s", ex)
        return 0


@router.post("/auction/import-date")
def import_auction_date(date: str = ""):
    """从项目根的 竞价数据_YYYY-MM-DD.xlsx 手动导入指定日期的竞价数据到数据库。

    用于 xlsx 已生成但未入库（如当日盘前补导历史数据）的情况。
    """
    if not date:
        return _err("缺少 date 参数（YYYY-MM-DD）")
    xlsx = _PROJECT_ROOT / f"竞价数据_{date}.xlsx"
    if not xlsx.exists():
        return _err(f"未找到 {xlsx.name}")
    db = _get_db(writable=True)
    if db is None:
        return _err("no database")
    try:
        cur = db.cursor()
        existing = cur.execute("SELECT COUNT(*) FROM auction WHERE date=?", (date,)).fetchone()[0]
        imported = _import_auction_excel(db, date)
        if imported == 0:
            return _err(f"导入失败（{xlsx.name} 读取出错）")
        return _ok(count=imported, date=date, existed=existing)
    finally:
        db.close()


def _check_auction_time() -> tuple[bool, dict | None]:
    """Check if auction collection is allowed.

    Returns (blocked, response). If blocked, response contains the payload to return.
    After 09:30, checks DB first; if empty, tries importing from Excel file.
    """
    now = datetime.now()
    after_cutoff = now.hour > 9 or (now.hour == 9 and now.minute >= 30)
    if not after_cutoff:
        return False, None

    db = _get_db(writable=True)
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

    from data.trading_calendar import is_trading_day
    if not is_trading_day(now):
        return _err("当前为非交易日（周末/节假日），不采集竞价数据", status="not_trading_day")

    blocked, resp = _check_auction_time()
    if blocked:
        return resp

    db = _get_db(writable=True)
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

        # 预加载昨日收盘（用于 prev_close 兜底：竞价时段腾讯 fields[4] 可能为空）
        cols = {r[1] for r in db.execute("PRAGMA table_info(daily_kline)").fetchall()}
        dc = "trade_date" if "trade_date" in cols else "date"
        prev_close_map: dict[str, float] = {}
        try:
            for r in db.execute(f"SELECT code, close FROM daily_kline WHERE {dc}=?", (latest_date,)).fetchall():
                prev_close_map[r[0]] = float(r[1])
        except Exception:
            pass

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
            # 腾讯 fields[37]=amount 单位是"万元"；统一存"万元"
            amount = round(basic["amount"], 2)
            # 竞价期间 price(fields[3]) 经常为 0，用 open(fields[5]) 作为竞价价兜底
            price = basic["price"] if basic["price"] > 0 else basic["open"]
            open_px = basic["open"]
            name = fields[1]
            prev_close = float(fields[4]) if fields[4] else 0
            # 竞价时 prev_close(fields[4]) 也常为 0，从 daily_kline 兜底取
            if prev_close <= 0 and code in prev_close_map:
                prev_close = prev_close_map[code]
            # bare_code 对应 prev_close_map 里带前缀的 code
            if prev_close <= 0:
                bare_tmp = code[2:] if code.startswith(("sh", "sz", "bj")) else code
                for _pfx in ("sh", "sz", "bj"):
                    if (_pfx + bare_tmp) in prev_close_map:
                        prev_close = prev_close_map[_pfx + bare_tmp]
                        break
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
                df = pd.DataFrame(rows, columns=['日期', '代码', '名称', '竞价量(手)', '竞价额(万元)', '竞价价', '开盘价', '采集时间', '昨收'])
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
        return {"stocks": [], "leaders": [], "stats": None, "error": str(e)}
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

        all_codes = set(d1_map) | set(d2_map)
        if not all_codes:
            return {"date1": date1, "date2": date2, "gainers": [], "losers": [],
                    "increase": 0, "decrease": 0, "total": 0}

        # Compute diff list first (no DB needed)
        # date1 = 今日, date2 = 昨日；vol_today 应为今天的量，vol_prev 为昨天的量
        diff = []
        for code in all_codes:
            v1 = d1_map.get(code, {}).get("vol", 0) or 0
            v2 = d2_map.get(code, {}).get("vol", 0) or 0
            name = d1_map.get(code, d2_map.get(code, {})).get("name", "")
            chg = v1 - v2
            pct = round((v1 - v2) / v2 * 100, 2) if v2 else 0
            info = d1_map.get(code) or d2_map.get(code) or {}
            diff.append({
                "code": code, "name": name,
                "vol_today": v1, "vol_prev": v2,
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


def _board_max_pct(code: str, name: str = "") -> float:
    """涨跌停比例（统一口径，见 data/board.py）。"""
    from data.board import board_limit_pct
    return board_limit_pct(code, name) * 100


def _is_limit_up(code: str, price: float, prev_close: float, name: str = "") -> bool:
    """Check if price is at limit-up (涨停) for the given stock. 统一口径见 data/board.py."""
    from data.board import is_limit_up
    return is_limit_up(code, price, prev_close, name)


def _limit_pct(code: str, name: str = "") -> float:
    """Return the limit-up percentage threshold for the given stock code. 统一口径见 data/board.py."""
    from data.board import limit_up_ratio
    return (limit_up_ratio(code, name) - 1.0) * 100


# ----------------------------------------------------------------------------
# 涨停次日竞价预期（「明礼队长」淘股吧方法论）
# 昨日涨停股的今日竞价，用「价（高开幅度）+ 量（竞价量能）」两变量打预期等级，
# 分 C1~C6 六种组合，直接对应次日操作。封板时间决定高开预期带。
# ----------------------------------------------------------------------------
# 封板时间 → 高开预期带（(不及下限, 符合下限, 超预期下限)，单位 %）
_SEAL_BANDS = {
    "一字":   (6, 9, 9),
    "9:45前": (4, 6, 6),
    "午前板": (2, 4, 4),
    "午后板": (0, 2, 2),
    "尾盘板": (0, 0, 0),
}


def _seal_band(first_seal: str, last_seal: str) -> str:
    """按昨日「首次封板时间」归类到 5 档预期带。

    first_seal/last_seal 形如 '092500'/'145027'（东财涨停池首次/最后封板时间 HHMMSS）。
    """
    if not first_seal:
        return "午前板"  # 拿不到时给中性档（2-4%）
    t = int(first_seal[:4]) if first_seal[:4].isdigit() else 9999
    last = int(last_seal[:4]) if last_seal and last_seal[:4].isdigit() else 9999
    if t <= 925 and last <= 925:
        return "一字"      # 竞价即封死且全天未开
    if t <= 945:
        return "9:45前"
    if t <= 1130:
        return "午前板"
    if t <= 1400:
        return "午后板"
    return "尾盘板"


def _price_level(band: str, open_pct) -> str:
    """价预期：按预期带把今日竞价高开%分为 超预期/符合/不及预期。"""
    if open_pct is None or band not in _SEAL_BANDS:
        return "未知"
    bad, ok, strong = _SEAL_BANDS[band]
    if open_pct > strong and strong > bad:
        return "超预期"
    if open_pct >= bad:
        return "符合预期"
    return "不及预期"


def _vol_level(auction_amount_wan, yest_amount_yuan) -> str:
    """量能：竞价量能 = 今竞价额 ÷ 昨日总成交额。

    简化标准（文章）：昨日成交额 <10 亿 → 达标需 ≥10%；≥10 亿 → 达标需 ≥8%。
    返回值 (level, pct)：(达标/不足, 竞价量能百分比)。
    """
    if auction_amount_wan is None or not yest_amount_yuan or yest_amount_yuan <= 0:
        return "未知", None
    pct = auction_amount_wan * 1e4 / yest_amount_yuan * 100
    need = 8 if yest_amount_yuan >= 1e9 else 10
    return ("达标" if pct >= need else "不足"), round(pct, 2)


# 6 组合标签/操作（含颜色含义，前端可据 colour 上色）
_COMBOS = {
    ("超预期", "达标"): ("C1", "价超量足", "资金抢筹·敢加仓", "red"),
    ("超预期", "不足"): ("C2", "价超量少", "诱多陷阱·别追", "orange"),
    ("符合预期", "达标"): ("C3", "价合量足", "看开盘承接", "blue"),
    ("符合预期", "不足"): ("C4", "价合量少", "弱分歧·先落袋", "gray"),
    ("不及预期", "达标"): ("C5", "价不及量足", "分歧洗盘·看修复", "purple"),
    ("不及预期", "不足"): ("C6", "价不及量少", "最危险·核按钮", "black"),
}


def _combo(price_level: str, vol_level: str) -> dict:
    """价×量 → C1~C6 组合标签、标题、操作建议、颜色。"""
    key = (price_level, vol_level)
    if key not in _COMBOS:
        return {"combo": None, "label": "未知", "action": "", "color": "gray"}
    combo, label, action, color = _COMBOS[key]
    return {"combo": combo, "label": label, "action": action, "color": color}


def _fetch_zt_pool_map(date_yyyymmdd: str) -> dict:
    """东财涨停池 → {6位代码: {seal_time, last_seal, consec, turnover_amount}}。

    用「首次/最后封板时间」定预期带、用昨日成交额定量能。
    拿不到（非 akshare / 网络失败）返回空 dict，调用方降级为只有价预期。
    """
    try:
        import akshare as ak
        zt = ak.stock_zt_pool_em(date=date_yyyymmdd)
        if zt is None or getattr(zt, "empty", True):
            return {}
    except Exception as e:
        _log.warning("zt_pool fetch failed %s: %s", date_yyyymmdd, e)
        return {}
    out = {}
    for _, r in zt.iterrows():
        code = str(r.get("代码", "")).zfill(6)
        try:
            consec = int(r.get("连板数") or 0)
        except (TypeError, ValueError):
            consec = 0
        try:
            t_amt = float(r.get("成交额") or 0)  # 元
        except (TypeError, ValueError):
            t_amt = 0
        out[code] = {
            "seal_time": str(r.get("首次封板时间", "") or ""),
            "last_seal": str(r.get("最后封板时间", "") or ""),
            "consec": consec,
            "turnover_amount": t_amt,
        }
    return out


@router.get("/auction/limit-up-compare")
def get_auction_limit_up_compare(date1: str = "", date2: str = ""):
    """Compare auction volumes of yesterday's limit-up stocks vs today's auction limit-up stocks.
    
    Uses daily_kline close prices for yesterday's limit-up detection,
    and auction table for today's auction limit-up detection.
    
    Args:
        date1: today's date (YYYY-MM-DD)
        date2: yesterday's date (YYYY-MM-DD)
    """
    if not date1 or not date2:
        return {"prev_limitup": [], "today_limitup": [], "both_limitup": []}
    db = _get_db()
    if db is None:
        return {"prev_limitup": [], "today_limitup": [], "both_limitup": []}
    try:
        cur = db.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(daily_kline)").fetchall()}
        dc = "trade_date" if "trade_date" in cols else "date"
        # date2 → 与 daily_kline 日期列一致的类型
        d2_bound = int(date2.replace("-", "")) if dc == "trade_date" else date2

        # Find previous trading day before date2
        cur.execute(
            f"SELECT MAX({dc}) FROM daily_kline WHERE {dc} < ?",
            (d2_bound,),
        )
        prev_trade_date = cur.fetchone()[0]
        if not prev_trade_date:
            return {"prev_limitup": [], "today_limitup": [], "both_limitup": []}

        # Get stocks that closed at limit-up on date2 (yesterday)
        # Need to handle prefix: daily_kline stores codes with prefix (sh/sz),
        # auction table stores without prefix
        cur.execute(
            "SELECT c.code, c.close, p.close as prev_close "
            "FROM daily_kline c "
            f"JOIN daily_kline p ON c.code = p.code AND p.{dc} = ? "
            f"WHERE c.{dc} = ? AND p.close > 0",
            (prev_trade_date, d2_bound),
        )
        prev_limitup_codes = set()
        prev_limitup_close = {}  # code_no_prefix → close
        for r in cur.fetchall():
            code_full = r[0]
            close = r[1]
            prev_close = r[2]
            if prev_close <= 0:
                continue
            # Strip prefix for matching with auction table
            code_clean = code_full[2:] if code_full.startswith(("sh", "sz", "bj")) else code_full
            if _is_limit_up(code_clean, close, prev_close):
                prev_limitup_codes.add(code_clean)
                prev_limitup_close[code_clean] = close

        # Get date2 auction data
        cur.execute(
            "SELECT code, name, auction_vol, auction_amount, auction_price, prev_close "
            "FROM auction WHERE date=?",
            (date2,),
        )
        prev_auction = {}
        for r in cur.fetchall():
            prev_auction[r[0]] = {"name": r[1], "vol": r[2] or 0, "amount": r[3] or 0,
                                  "price": r[4] or 0, "prev_close": r[5] or 0}

        # Get date1 (today) auction data
        cur.execute(
            "SELECT code, name, auction_vol, auction_amount, auction_price, prev_close "
            "FROM auction WHERE date=?",
            (date1,),
        )
        today_auction = {}
        for r in cur.fetchall():
            today_auction[r[0]] = {"name": r[1], "vol": r[2] or 0, "amount": r[3] or 0,
                                   "price": r[4] or 0, "prev_close": r[5] or 0}

        # 同花顺概念映射（涨停票概念展示）
        concepts_map = {}
        try:
            from data.auction_concept_analysis import fetch_concepts
            concepts_map = fetch_concepts(cur)
        except Exception:
            _log.warning("auction concepts load failed", exc_info=True)

        # Classify today's auction limit-up stocks
        today_limitup_codes = set()
        for code, info in today_auction.items():
            if _is_limit_up(code, info["price"], info["prev_close"], info.get("name", "")):
                today_limitup_codes.add(code)

        # 昨日东财涨停池（封板时间/连板数/成交额）→ 涨停次日竞价预期（「明礼队长」方法论）
        zt_map = _fetch_zt_pool_map(str(date2).replace("-", ""))

        def build_stock(code):
            p = prev_auction.get(code)
            t = today_auction.get(code)
            name = (p or t or {}).get("name", "")
            p_vol = (p or {}).get("vol", 0) or 0
            t_vol = (t or {}).get("vol", 0) or 0
            p_amt = (p or {}).get("amount", 0) or 0
            t_amt = (t or {}).get("amount", 0) or 0
            p_price = (p or {}).get("price", 0) or 0
            t_price = (t or {}).get("price", 0) or 0
            t_pc = (t or {}).get("prev_close", 0) or 0
            p_pc = (p or {}).get("prev_close", 0) or 0
            prev_close = t_pc or p_pc
            vol_chg = t_vol - p_vol
            vol_pct = round(t_vol / p_vol * 100, 2) if p_vol > 0 else 999.0
            auction_chg = round((t_price - prev_close) / prev_close * 100, 2) if prev_close and t_price else None
            is_prev = code in prev_limitup_codes
            is_today = code in today_limitup_codes
            # 涨停次日竞价预期：仅对「昨日涨停」股算（价+量 → C1~C6）
            biz = {}
            if is_prev:
                zt = zt_map.get(code) or {}
                band = _seal_band(zt.get("seal_time", ""), zt.get("last_seal", ""))
                plev = _price_level(band, auction_chg)
                vlev, vpct = _vol_level(t_amt, zt.get("turnover_amount"))
                biz = {
                    "band": band,
                    "first_seal": zt.get("seal_time", ""),
                    "consec_boards": zt.get("consec", 0),
                    "yest_amount": zt.get("turnover_amount", 0),
                    "price_level": plev,
                    "vol_level": vlev,
                    "vol_pct_auction": vpct,
                    "combo": _combo(plev, vlev),
                }
            return {
                "code": code, "name": name,
                "is_prev_limitup": is_prev,
                "is_today_limitup": is_today,
                "vol_today": t_vol, "vol_prev": p_vol,
                "vol_chg": vol_chg, "vol_pct": vol_pct,
                "amt_today": t_amt, "amt_prev": p_amt,
                "price_today": t_price, "price_prev": p_price,
                "prev_close": prev_close,
                "auction_chg_today": auction_chg,
                "concepts": concepts_map.get(code, []),
                "auction_expectation": biz,
            }

        all_codes = prev_limitup_codes | today_limitup_codes
        both = [build_stock(c) for c in sorted(prev_limitup_codes & today_limitup_codes)]
        prev_only = [build_stock(c) for c in sorted(prev_limitup_codes - today_limitup_codes)]
        today_only = [build_stock(c) for c in sorted(today_limitup_codes - prev_limitup_codes)]

        both.sort(key=lambda x: x["vol_today"], reverse=True)
        prev_only.sort(key=lambda x: x["vol_today"], reverse=True)
        today_only.sort(key=lambda x: x["vol_today"], reverse=True)

        # 昨日涨停股实时涨跌幅（腾讯接口，用于「昨日涨停」表替换量变化列）
        try:
            from data.tencent_quotes import add_prefix, fetch_detail
            prev_codes = [s["code"] for s in prev_only + both]
            _rt = {}
            for i in range(0, len(prev_codes), 50):
                batch = [add_prefix(c) for c in prev_codes[i:i + 50]]
                if not batch:
                    continue
                quotes = fetch_detail(batch)
                for full_code, q in quotes.items():
                    bare = full_code[2:] if full_code[:2] in ("sh", "sz", "bj") else full_code
                    _rt[bare] = q.get("change_pct")
            for s in prev_only + both:
                s["realtime_chg_pct"] = _rt.get(s["code"])
        except Exception:
            _log.warning("auction prev_limitup realtime fetch failed", exc_info=True)
            for s in prev_only + both:
                s["realtime_chg_pct"] = None

        return {
            "prev_limitup": prev_only,
            "today_limitup": today_only,
            "both_limitup": both,
            "date1": date1, "date2": date2,
            "prev_count": len(prev_only) + len(both),
            "today_count": len(today_only) + len(both),
            "both_count": len(both),
        }
    except Exception as e:
        _log.warning("auction limit-up-compare failed", exc_info=True)
        return {"prev_limitup": [], "today_limitup": [], "both_limitup": []}
    finally:
        db.close()


@router.get("/auction/search")
def get_auction_search(keyword: str = "", date1: str = "", date2: str = "", top: int = 30):
    """Search stocks by keyword across two dates and compare auction data."""
    if not keyword or not date1 or not date2:
        return {"results": [], "total": 0}
    db = _get_db()
    if db is None:
        return {"results": [], "total": 0}
    try:
        cur = db.cursor()
        like = f"%{keyword}%"
        cur.execute(
            "SELECT code, name, auction_vol, auction_amount, auction_price, collect_time, prev_close "
            "FROM auction WHERE date=? AND (code LIKE ? OR name LIKE ?)",
            (date1, like, like),
        )
        d1_map = {}
        for r in cur.fetchall():
            d1_map[r[0]] = {"name": r[1], "vol": r[2], "amount": r[3], "price": r[4], "time": r[5], "prev_close": r[6] or 0}
        cur.execute(
            "SELECT code, name, auction_vol, auction_amount, auction_price, collect_time, prev_close "
            "FROM auction WHERE date=? AND (code LIKE ? OR name LIKE ?)",
            (date2, like, like),
        )
        d2_map = {}
        for r in cur.fetchall():
            d2_map[r[0]] = {"name": r[1], "vol": r[2], "amount": r[3], "price": r[4], "time": r[5], "prev_close": r[6] or 0}

        all_codes = set(d1_map) | set(d2_map)
        results = []
        for code in sorted(all_codes):
            t = d1_map.get(code)
            p = d2_map.get(code)
            if t and p:
                t_vol, p_vol = t["vol"] or 0, p["vol"] or 0
                vol_pct = round(t_vol / p_vol * 100, 2) if p_vol > 0 else 999.0
                amt_pct = round(t["amount"] / p["amount"] * 100, 2) if (p.get("amount") or 0) > 0 else 0
                results.append({
                    "code": code, "name": t["name"],
                    "is_new": False, "is_gone": False,
                    "vol_today": t["vol"] or 0, "vol_prev": p["vol"] or 0,
                    "vol_pct": vol_pct,
                    "amt_today": t["amount"] or 0, "amt_prev": p["amount"] or 0,
                    "amt_pct": amt_pct,
                    "price_today": t["price"] or 0, "price_prev": p["price"] or 0,
                    "prev_close": t["prev_close"],
                })
            elif t and not p:
                results.append({
                    "code": code, "name": t["name"],
                    "is_new": True, "is_gone": False,
                    "vol_today": t["vol"] or 0, "vol_prev": 0,
                    "vol_pct": 999.0,
                    "amt_today": t["amount"] or 0, "amt_prev": 0,
                    "amt_pct": 0,
                    "price_today": t["price"] or 0, "price_prev": 0,
                    "prev_close": t["prev_close"],
                })
            elif p and not t:
                results.append({
                    "code": code, "name": p["name"],
                    "is_new": False, "is_gone": True,
                    "vol_today": 0, "vol_prev": p["vol"] or 0,
                    "vol_pct": 0,
                    "amt_today": 0, "amt_prev": p["amount"] or 0,
                    "amt_pct": 0,
                    "price_today": 0, "price_prev": p["price"] or 0,
                    "prev_close": p["prev_close"],
                })

        results.sort(key=lambda x: (0 if x["is_new"] else 1, 0 if x["is_gone"] else 1, -x["vol_pct"]))
        new_count = sum(1 for r in results if r["is_new"])
        gone_count = sum(1 for r in results if r["is_gone"])
        up = sum(1 for r in results if not r["is_new"] and not r["is_gone"] and r["vol_pct"] > 120)
        down = sum(1 for r in results if not r["is_new"] and not r["is_gone"] and r["vol_pct"] < 80)

        return {
            "date1": date1, "date2": date2,
            "keyword": keyword,
            "results": results[:top],
            "total": len(results),
            "new_count": new_count, "gone_count": gone_count,
            "up": up, "down": down,
        }
    except Exception as e:
        _log.warning("auction search failed: %s", e, exc_info=True)
        return {"results": [], "total": 0}
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


@router.get("/auction/sector-strength")
def get_auction_sector_strength(
    date: str = "",
    top_sectors: int = 15,
    top_stocks: int = 5,
    source: str = "ths_industry",
) -> dict:
    """竞价板块强度：按同花顺行业分组排名，并从最强板块挑可交易最强个股。

    Args:
        date: 日期 YYYY-MM-DD，默认取最近一个竞价价完整的交易日
        top_sectors: 返回最强板块数量
        top_stocks: 每个板块返回的个股数量
        source: 目前仅 'ths_industry'（同花顺行业）；预留扩展
    """
    try:
        from data.auction_sector_strength import sector_strength

        return sector_strength(
            date=date, top_sectors=top_sectors, top_stocks=top_stocks, source=source
        )
    except Exception as e:
        _log.warning("[sector-strength] FAILED: %s", e, exc_info=True)
        return {"date": date, "source": source, "sectors": [], "error": str(e)}


@router.get("/auction/gap-up")
def get_auction_gap_up(
    date: str = "",
    min_chg: float = 3.0,
    max_chg: float = 9.0,
    min_vol_ratio: float = 1.0,
    limit: int = 100,
) -> dict:
    """竞价跳空高开筛选。

    筛选条件（严格按需求，无额外门槛）：
      - 竞价涨幅 [min_chg%, max_chg%]（默认 3%~9%，排除一字涨停和微涨）
      - 量比 ≥ min_vol_ratio（默认 1，竞价量必须大于前日竞价量）
      - 排除 ST/退市股
    按竞价金额倒序。返回字段含 gap_break_prev_high（是否跳空突破昨日K线高点）。
    """
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
        return {"date": "", "stocks": []}

    # 昨日竞价日期
    prev_date = None
    db = _get_db()
    if db:
        try:
            dr = db.execute(
                "SELECT DISTINCT date FROM auction WHERE date < ? ORDER BY date DESC LIMIT 1",
                (date,),
            ).fetchone()
            if dr:
                prev_date = dr[0]
        finally:
            db.close()

    db = _get_db()
    if db is None:
        return {"date": date, "stocks": []}
    try:
        # 直接检测当前库的日期列名（避免 get_date_col() 误判到其它库）
        cols = {r[1] for r in db.execute("PRAGMA table_info(daily_kline)").fetchall()}
        date_col = "trade_date" if "trade_date" in cols else "date"
        is_int = date_col == "trade_date"

        cur = db.cursor()
        # 先按最宽门槛拉候选（覆盖 30cm 北交所上限），Python层按板块二次过滤
        sql_max = max(max_chg, 30.0)
        cur.execute(
            """
            SELECT code, name, auction_price, prev_close, auction_vol, auction_amount
            FROM auction
            WHERE date=? AND prev_close>0 AND auction_price>0
              AND (auction_price*1.0/prev_close) >= ?
              AND (auction_price*1.0/prev_close) <= ?
              AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
            ORDER BY auction_amount DESC
            LIMIT ?
            """,
            (date, 1 + min_chg / 100, 1 + sql_max / 100, limit * 2),
        )
        today_rows = cur.fetchall()
        if not today_rows:
            return {"date": date, "stocks": []}

        # 板块区分：创业板/科创板/北交所用真实涨跌停上限，主板用调用方 max_chg（排除一字涨停/微涨）
        from data.board import board_limit_pct as _board_limit_pct

        def _board_max_chg(code: str) -> float:
            bare = code[2:] if code.startswith(("sh", "sz", "bj")) else code
            if bare.startswith(("300", "301", "302", "688", "689", "8", "4")):
                return _board_limit_pct(bare) * 100
            return max_chg  # 默认 9%（主板）

        filtered = []
        for r in today_rows:
            code = r[0]
            ap, pc = r[2], r[3]
            if pc and pc > 0 and ap:
                chg = (ap / pc - 1) * 100
                board_max = _board_max_chg(code)
                if min_chg <= chg <= board_max:
                    filtered.append(r)
        today_rows = filtered
        if not today_rows:
            return {"date": date, "stocks": []}

        # 昨日竞价量
        codes = [r[0] for r in today_rows]
        prev_auction_map: dict = {}
        if prev_date:
            placeholders = ",".join("?" * len(codes))
            prev_rs = cur.execute(
                f"SELECT code, auction_vol FROM auction WHERE date=? AND code IN ({placeholders})",
                [prev_date] + codes,
            ).fetchall()
            prev_auction_map = {r[0]: r[1] for r in prev_rs}

        # 昨收K线 high（判断是否跳空突破前高）
        prev_date_val = None
        if prev_date:
            prev_date_val = int(prev_date.replace("-", "")) if is_int else prev_date
        daily_high_map: dict = {}
        if prev_date_val:
            prefixed_codes = []
            for c in codes:
                if c.startswith(("sh", "sz")):
                    prefixed_codes.append(c)
                else:
                    # auction 存的是裸代码，daily_kline 可能带前缀
                    if c.startswith("6"):
                        prefixed_codes.append("sh" + c)
                    else:
                        prefixed_codes.append("sz" + c)
            # 同时尝试裸代码和带前缀代码
            all_codes = list(dict.fromkeys(codes + prefixed_codes))
            placeholders2 = ",".join("?" * len(all_codes))
            daily_rows = cur.execute(
                f"SELECT code, high FROM daily_kline WHERE {date_col}=? AND code IN ({placeholders2})",
                [prev_date_val] + all_codes,
            ).fetchall()
            code_to_high: dict = {}
            for r in daily_rows:
                code_to_high[r[0]] = r[1]
            # 映射回 auction 里的裸代码
            for i, bare in enumerate(codes):
                pre = prefixed_codes[i]
                h = code_to_high.get(bare) or code_to_high.get(pre)
                if h:
                    daily_high_map[bare] = h

        stocks: list[dict] = []
        for r in today_rows:
            code, name, auction_price, prev_close, auction_vol, auction_amount = r
            chg_pct = (auction_price / prev_close - 1) * 100
            prev_vol = prev_auction_map.get(code) or 0
            vol_ratio = (auction_vol / prev_vol) if prev_vol > 0 else None
            # 量比过滤：竞价量必须大于前日竞价量；前日无数据时不做过滤（避免新上市/首次采集被误伤）
            if vol_ratio is not None and vol_ratio < min_vol_ratio:
                continue
            prev_high = daily_high_map.get(code)
            # 是否跳空突破昨日高点
            gap_break_prev_high = bool(prev_high and auction_price > prev_high)

            stocks.append({
                "code": code,
                "name": name,
                "auction_price": auction_price,
                "prev_close": prev_close,
                "chg_pct": round(chg_pct, 2),
                "auction_vol": auction_vol,
                "auction_amount_wan": round(auction_amount, 0) if auction_amount else 0,
                "prev_auction_vol": prev_vol,
                "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
                "prev_high": prev_high,
                "gap_break_prev_high": gap_break_prev_high,
            })

        # 给每只股票匹配同花顺行业板块（L2），按行业竞价平均涨幅倒序
        try:
            from collections import defaultdict as _dd

            # 1) 裸代码 -> 带前缀代码（用于 stock_ths_industry 查询）
            def _to_prefixed(bare: str) -> str:
                if bare.startswith(("sh", "sz", "bj")):
                    return bare
                if bare.startswith("6"):
                    return "sh" + bare
                if bare.startswith(("0", "3")):
                    return "sz" + bare
                return "bj" + bare

            prefixed = [_to_prefixed(c) for c in codes]
            placeholders = ",".join("?" * len(prefixed))
            # 2) 查询每只股票的同花顺行业 L2
            ind_rows = cur.execute(
                f"SELECT code, industry_l2 FROM stock_ths_industry WHERE code IN ({placeholders})",
                prefixed,
            ).fetchall()
            code_to_l2 = {r[0]: r[1] for r in ind_rows if r[1]}

            # 3) 按行业分组，计算每组竞价平均涨幅
            ind_stocks: dict[str, list[float]] = _dd(list)
            for s in stocks:
                l2 = code_to_l2.get(_to_prefixed(s["code"]))
                if l2:
                    ind_stocks[l2].append(s["chg_pct"])
            industry_chg = {nm: round(sum(vs) / len(vs), 2) for nm, vs in ind_stocks.items() if vs}

            # 4) 给每只股票挂 top_industry / top_industry_chg
            for s in stocks:
                l2 = code_to_l2.get(_to_prefixed(s["code"]))
                s["top_industry"] = l2
                s["top_industry_chg"] = industry_chg.get(l2) if l2 else None
            # 按行业板块涨幅倒序；同分按竞价金额倒序
            stocks.sort(
                key=lambda s: (-(s.get("top_industry_chg") or -999), -(s.get("auction_amount_wan") or 0)),
            )
        except Exception as e:
            _log.warning("auction gap-up: top_industry matching failed: %s", e)

        return {"date": date, "stocks": stocks}
    finally:
        db.close()


def _auction_ai_analysis(data: dict, log=None) -> dict:
    """AI 竞价分析核心：汇总当日竞价数据，调用 LLM 生成分析报告。

    log 回调时，把各阶段进度写入日志（供 /auction/ai-analysis/run 后台任务实时回显）；
    无回调时落到文件 logs/ai_analysis/auction_ai_analysis_YYYYMMDD.log。
    Body: { "date": "YYYY-MM-DD", "concept_source": "industry|concept",
            "web_answers": [{target,label,answer}...] }
    web_answers 非空时，把已收到的豆包/DeepSeek 多源回答交给项目 LLM 交叉验证并追加最终结论。
    """
    from utils.logging_setup import get_run_logger
    _run_logger = get_run_logger("auction_ai_analysis", "ai_analysis")

    def log_line(msg: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        if log:
            log(line)
        else:
            _run_logger.info(msg)

    date_str = data.get("date", "")
    source = data.get("concept_source", "industry")

    if not date_str:
        db = _get_db()
        if db:
            try:
                r = db.execute("SELECT DISTINCT date FROM auction ORDER BY date DESC LIMIT 1").fetchone()
                if r:
                    date_str = r[0]
            except Exception:
                pass
            finally:
                db.close()
    if not date_str:
        return {"error": "无法确定竞价日期"}

    log_line(f"开始分析：{date_str}（板块源：{source}）")

    # 1) 汇总竞价数据
    sections: list[str] = [f"## 竞价日期: {date_str}"]

    # 1a) 板块分析
    try:
        from data.auction_concept_analysis import analyze_to_json
        concept_result = analyze_to_json(date_str, top_concepts=20, source=source)
        concepts = concept_result.get("concepts", [])
        if concepts:
            lines = ["### 板块竞价分析"]
            for c in concepts[:15]:
                sig = c.get("signal", "") or ""
                anchor = c.get("anchor")
                zhongjun = c.get("zhongjun")
                line = (
                    f"- {c['tag']}: 评分{c['score']:.0f}, 红盘率{c['red_ratio']*100:.0f}%, "
                    f"均涨幅{c['avg_chg']:+.2f}%, {c['n']}只"
                )
                if sig:
                    line += f", 信号:{sig}"
                if anchor:
                    line += f" | 锚点:{anchor.get('name','')}({anchor.get('code','')}){anchor.get('chg_pct',0):+.2f}%"
                if zhongjun:
                    line += f" | 中军:{zhongjun.get('name','')}"
                if c.get("max_limit", 0) > 0:
                    line += f" | 最高板:{c['max_limit']}板"
                lines.append(line)
            sections.append("\n".join(lines))
    except Exception as e:
        _log.warning("auction AI: concept analysis failed: %s", e)

    # 1b) 涨停竞价对比
    try:
        db = _get_db()
        if db:
            cur = db.cursor()
            # 今日竞价涨停数（宽查候选，Python按板块口径过滤）
            cur.execute(
                "SELECT code, name, auction_price, prev_close FROM auction WHERE date=? AND prev_close>0 AND auction_price > prev_close*1.02",
                (date_str,),
            )
            today_lu = [r for r in cur.fetchall() if _is_limit_up(r[0], r[2], r[3], r[1])]
            # 昨日涨停今日竞价
            cur.execute("SELECT DISTINCT date FROM auction WHERE date < ? ORDER BY date DESC LIMIT 1", (date_str,))
            prev_row = cur.fetchone()
            prev_lu = []
            if prev_row:
                prev_date = prev_row[0]
                cur.execute(
                    "SELECT code, name, auction_price, prev_close FROM auction WHERE date=? AND prev_close>0 AND auction_price > prev_close*1.02",
                    (prev_date,),
                )
                prev_lu = [r for r in cur.fetchall() if _is_limit_up(r[0], r[2], r[3], r[1])]
            db.close()

            lu_lines = ["### 涨停竞价分析"]
            lu_lines.append(f"- 今日竞价涨停: {len(today_lu)}只")
            if today_lu:
                top5 = today_lu[:10]
                lu_lines.append("  " + ", ".join(f"{r[1]}({r[0]})" for r in top5))
            lu_lines.append(f"- 昨日涨停股: {len(prev_lu)}只")
            if prev_lu:
                # 检查今日竞价表现
                if today_lu:
                    today_codes = {r[0] for r in today_lu}
                    both = [r for r in prev_lu if r[0] in today_codes]
                    lu_lines.append(f"- 昨日涨停今日竞价继续涨停: {len(both)}只")
                    if both:
                        lu_lines.append("  " + ", ".join(f"{r[1]}({r[0]})" for r in both[:10]))
            sections.append("\n".join(lu_lines))
    except Exception as e:
        _log.warning("auction AI: limit-up analysis failed: %s", e)

    # 1c) 竞价量排行 TOP10
    try:
        db = _get_db()
        if db:
            cur = db.cursor()
            cur.execute(
                "SELECT code, name, auction_vol, auction_amount, auction_price, prev_close FROM auction WHERE date=? ORDER BY auction_vol DESC LIMIT 10",
                (date_str,),
            )
            top_stocks = cur.fetchall()
            db.close()
            if top_stocks:
                vol_lines = ["### 竞价量排行 TOP10"]
                for i, r in enumerate(top_stocks, 1):
                    chg = ""
                    if r[5] and r[5] > 0 and r[4] and r[4] > 0:
                        chg_pct = (r[4] / r[5] - 1) * 100
                        chg = f", 竞价涨幅{chg_pct:+.2f}%"
                    vol_lines.append(f"{i}. {r[1]}({r[0]}): 竞价量{r[2]:,}, 金额{r[3]:,.0f}元{chg}")
                sections.append("\n".join(vol_lines))
    except Exception as e:
        _log.warning("auction AI: top stocks failed: %s", e)

    # 1d) 自选股竞价分析
    try:
        exp_state = _read_json(_PAPER_DIR / "expectation_state.json")
        positions = exp_state.get("positions", []) if isinstance(exp_state, dict) else []
        if positions:
            # 获取昨日竞价日期用于量比计算
            db = _get_db()
            prev_date = None
            if db:
                try:
                    dr = db.execute(
                        "SELECT DISTINCT date FROM auction WHERE date < ? ORDER BY date DESC LIMIT 1",
                        (date_str,),
                    ).fetchone()
                    if dr:
                        prev_date = dr[0]
                finally:
                    db.close()

            code_list = [p.get("code", "") for p in positions if p.get("code")]
            bare_list = [c[2:] if c.startswith(("sh", "sz")) else c for c in code_list]
            search_codes = list(dict.fromkeys(bare_list + code_list))

            db = _get_db()
            today_map: dict = {}
            prev_map: dict = {}
            if db and search_codes:
                try:
                    placeholders = ",".join("?" * len(search_codes))
                    # 今日竞价
                    today_rows = db.execute(
                        f"SELECT code, name, auction_vol, auction_amount, auction_price, prev_close "
                        f"FROM auction WHERE date=? AND code IN ({placeholders})",
                        [date_str] + search_codes,
                    ).fetchall()
                    today_map = {}
                    for r in today_rows:
                        today_map[r[0]] = {
                            "name": r[1], "vol": r[2], "amount": r[3],
                            "price": r[4], "prev_close": r[5],
                        }
                    # 昨日竞价
                    if prev_date:
                        prev_rows = db.execute(
                            f"SELECT code, auction_vol FROM auction WHERE date=? AND code IN ({placeholders})",
                            [prev_date] + search_codes,
                        ).fetchall()
                        prev_map = {r[0]: r[1] for r in prev_rows}
                finally:
                    db.close()

            wl_lines = ["### 自选股竞价分析"]
            n_watch = 0
            for i, p in enumerate(positions):
                code = p.get("code", "")
                name = p.get("name", "")
                if not code:
                    continue
                bare = bare_list[i] if i < len(bare_list) else (code[2:] if code.startswith(("sh", "sz")) else code)
                t = today_map.get(bare) or today_map.get(code) or {}
                price = t.get("price") or 0
                prev_close = t.get("prev_close") or p.get("prev_close") or 0
                vol_amount = t.get("amount") or 0  # 竞价金额（auction_amount）
                vol_prev = prev_map.get(bare) or prev_map.get(code) or 0
                # 竞价涨幅
                chg_pct = ((price / prev_close - 1) * 100) if (price and prev_close) else 0
                # 量比（今日竞价量 / 昨日竞价量）
                vol_ratio = (t.get("vol") or 0) / vol_prev if (vol_prev and vol_prev > 0) else 0
                # 支撑/压力位
                support = p.get("support") or 0
                resistance = p.get("resistance") or 0
                # 与支撑压力位关系
                pos_tag = ""
                if price and support and resistance:
                    if price <= support * 1.02:
                        pos_tag = "【贴近支撑位】"
                    elif price >= resistance * 0.98:
                        pos_tag = "【接近压力位】"
                    elif support < price < resistance:
                        pos_tag = "【支撑压力之间】"
                    elif price > resistance:
                        pos_tag = "【突破压力位⚠️】"
                    elif price < support:
                        pos_tag = "【跌破支撑位⚠️】"

                chg_str = f"竞价{chg_pct:+.2f}%" if (price and prev_close) else "无竞价价"
                vol_str = ""
                if t.get("vol"):
                    vol_str = f", 竞价量{(t.get('vol') or 0)/10000:.2f}万手"
                if vol_amount:
                    # auction_amount 单位为万元，转亿元/万元展示
                    vol_str += f", 额{vol_amount/10000:.2f}亿" if vol_amount >= 10000 else f", 额{vol_amount:.0f}万"
                if vol_ratio:
                    vol_str += f", 量较昨日{vol_ratio:.1f}倍"
                sr_str = ""
                if support and resistance:
                    sr_str = f" 支撑{support:.2f}/压力{resistance:.2f}"
                line = f"- {name}({code}): {chg_str}{vol_str}{pos_tag}{sr_str}"
                wl_lines.append(line)
                n_watch += 1
            if n_watch:
                sections.append("\n".join(wl_lines))
    except Exception as e:
        _log.warning("auction AI: watchlist analysis failed: %s", e)

    log_line("✓ 竞价数据汇总完成（板块 / 涨停对比 / 量排行 / 自选股）")

    if len(sections) <= 1:
        return {"error": f"日期 {date_str} 无竞价数据可分析"}

    summary = "\n\n".join(sections)

    # 2) 只综合豆包/DeepSeek 的回答：项目 LLM 不做自己的数据分析（不参与对提示词的解读）
    web_answers = data.get("web_answers") or []
    blocks = []
    for w in web_answers or []:
        if not isinstance(w, dict):
            continue
        label = (w.get("label") or w.get("target") or "AI")
        ans = (w.get("answer") or "").strip()
        if ans:
            blocks.append(f"### {label} 的回答\n{ans[:2000]}")
    if not blocks:
        return {"error": "没有可综合的回答：请先一键发送或手动粘贴豆包/DeepSeek 的回答，再做多源综合分析"}

    try:
        try:
            from dotenv import load_dotenv
            load_dotenv(_PROJECT_ROOT / ".env")
        except ImportError:
            pass

        from analysis.llm_analyzer import call_llm

        log_line(f"对 {len(blocks)} 个来源（豆包/DeepSeek）的回答做 LLM 多源综合…")
        synth_sys = (
            "你是 A 股短线竞价多源分析师。你的任务：只综合豆包与 DeepSeek 两个 AI 模型对同一份竞价数据的分析回答，"
            "结合下方本地竞价数据摘要做交叉验证，给出唯一最终判断。不要自行从本地数据摘要重新生成独立分析。\n"
            "要求：\n"
            "1. 观点对比：提炼各家核心判断，指出方向一致处与分歧点\n"
            "2. 数据验证：哪些观点与本地数据（板块强度/涨停数/量能/竞价涨幅）吻合，哪些缺乏支持\n"
            "3. 结论明确：给出今日资金主攻方向、重点板块与个股、风险点、建议动作，拒绝和稀泥\n"
            "只基于给定材料，禁止编造数字。"
        )
        synth_prompt = (
            f"### 本地竞价数据摘要（仅用于交叉验证，不要求你分析它）\n{summary[:4000]}\n\n"
            + "\n\n".join(blocks)
            + "\n\n请综合以上各家的回答，输出唯一的多源综合分析结论（含最终操作建议）。"
        )
        synthesis = call_llm(synth_prompt, model="mimo-v2.5-pro", system_prompt=synth_sys)
        log_line(f"✓ 多源 LLM 综合完成（{len(synthesis)} 字）")
        report = f"## 📊 多源 LLM 综合结论（豆包 + DeepSeek）\n\n{synthesis}"

        # 4) 落盘 md：按 AI 下拉阶段位置对应卡片 ①~④（stage=0→stage1.md, 1→stage2.md, ...）
        saved = ""
        stage_arg = data.get("stage")
        try:
            if stage_arg not in (None, "", "auto", "null", "None"):
                card = max(0, min(int(stage_arg), 3)) + 1
                path = _AI_REPORT_DIR / date_str / f"stage{card}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"# 竞价情绪 AI 分析 · {date_str} · 阶段{card}\n\n{report}",
                    encoding="utf-8",
                )
                saved = str(path.relative_to(_PROJECT_ROOT))
                log_line(f"✓ 结果已保存：{saved}")
        except Exception as exc:
            _log.warning("auction AI: save report failed: %s", exc)
        return {"report": report, "date": date_str, "summary": summary, "saved": saved}
    except Exception as e:
        detail = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail += " | body=" + str(resp.text[:500])
            except Exception:
                pass
        _log.warning("auction AI analysis failed: %s", detail)
        try:
            log_line(f"✗ 分析失败：{detail[:200]}")
        except Exception:
            pass
        return {"error": detail}


_AUCTION_AI_JOBS: dict[str, dict] = {}

@router.post("/auction/ai-analysis")
def auction_ai_analysis(data: dict) -> dict:
    """同步版：直接返回报告（竞价看板 AI tab 等旧调用方使用）。"""
    return _auction_ai_analysis(data)


@router.post("/auction/ai-analysis/run")
def auction_ai_analysis_run(data: dict) -> dict:
    """异步版：后台线程跑分析，实时日志写入内存 job，前端轮询 status 展示进度。"""
    task_id = uuid.uuid4().hex[:8]
    job = {"logs": [], "done": False, "result": None}
    _AUCTION_AI_JOBS[task_id] = job

    def _run():
        try:
            job["result"] = _auction_ai_analysis(data, log=job["logs"].append)
        except Exception as exc:  # noqa: BLE001
            job["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ 后台任务异常：{str(exc)[:200]}")
            job["result"] = {"error": str(exc)[:500]}
        finally:
            job["done"] = True

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}


@router.get("/auction/ai-analysis/status/{task_id}")
def auction_ai_analysis_status(task_id: str):
    """读取后台分析任务的实时日志；done=True 时附最终 result。"""
    job = _AUCTION_AI_JOBS.get(task_id)
    if not job:
        return {"done": False, "logs": [], "error": "任务不存在或已过期"}
    return {"done": job["done"], "logs": job["logs"], "result": job["result"]}

_LADDER_CACHE_DIR = _PAPER_DIR

def _ladder_cache_path(today_compact: str) -> Path:
    return _LADDER_CACHE_DIR / f"ladder_cache_{today_compact}.json"


def _fallback_ladder_date(today_compact: str) -> str | None:
    """盘前回退：返回最近交易日（比今天早的最新交易日，'YYYY-MM-DD'），数据库不可用/异常返回 None。"""
    try:
        db = _get_db()
        if db is None:
            return None
        try:
            latest = _latest_trade_date(db)
        finally:
            try:
                db.close()
            except Exception:
                pass
        if not latest:
            return None
        ds = str(latest).strip()
        if "-" in ds:
            compact = ds.replace("-", "")
        elif ds.isdigit():
            compact = ds
        else:
            return None
        if compact >= today_compact:
            return None
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    except Exception:
        return None


def _parse_cn_amount(s) -> float:
    """问财金额字段可能是 '1.23亿' / '4567万' / 纯数字(元)，统一转成元(float)。"""
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0
    mult = 1.0
    if s.endswith("亿"):
        mult = 1e8
        s = s[:-1]
    elif s.endswith("万"):
        mult = 1e4
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def _iwencai_first_match(row: dict, *names):
    """问财返回列名常带变动后缀(如 [20260901] 或 [20260819-20260901])，
    且语义相似的列名会变(封单额→隔夜单额、炸板次数→涨停开板次数、首次封板时间→最新首次涨停时间)。
    先做精确匹配，再按前缀匹配，兼容不同日期后缀与别名。"""
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    for n in names:
        for k, v in row.items():
            if k.startswith(n) and v not in (None, ""):
                return v
    for n in names:
        if n in row:
            return row[n]
    for n in names:
        for k, v in row.items():
            if k.startswith(n):
                return v
    return None


@router.get("/market/ladder")
def get_market_ladder():
    """Get limit-up ladder analysis via iwencai, with daily file cache.

    盘前回退：盘前（今日尚无涨停）时，以数据库最近交易日为回退日期展示（优先用该日缓存，否则在线查询）。
    """
    today_compact = date.today().strftime("%Y%m%d")
    cache_path = _ladder_cache_path(today_compact)
    from_path = "today"

    # Serve from cache if available
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached
    except Exception:
        pass

    # Cache miss — fetch from iwencai. 优先采集 IWENCAI_API_KEY（根项目 .env）。
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

        from analysis.external.iwencai import query_data

        today_query = (
            "今日涨停股票 剔除ST 剔除退市 股票代码 股票简称 收盘价 最新涨跌幅 连续涨停天数 "
            "首次封板时间 封单额 炸板次数 涨停原因 成交额"
        )
        raw = query_data(today_query)

        # 盘前回退：今日无数据时，以数据库最近交易日为回退日期（优先用该日缓存，否则在线查询）。
        if not raw:
            fallback_date = _fallback_ladder_date(today_compact)
            if not fallback_date:
                return {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": "暂无数据（盘前）"}
            fb_compact = fallback_date.replace("-", "")
            fb_cache = _ladder_cache_path(fb_compact)
            if fb_cache.exists():
                cached = json.loads(fb_cache.read_text(encoding="utf-8"))
                summary = cached.get("summary", "") + f"（回退至 {fb_compact}）"
                return dict(cached, summary=summary)
            raw = query_data(
                f"{fallback_date} 涨停股票 剔除ST 剔除退市 股票代码 股票简称 收盘价 最新涨跌幅 "
                "连续涨停天数 首次封板时间 封单额 炸板次数 涨停原因 成交额"
            )
            from_path = f"fallback:{fb_compact}"
            today_compact = fb_compact

        if not raw:
            result = {"ladder": [], "by_board": {}, "by_concept": {}, "stats": None, "summary": "暂无数据"}
            return result

        from data.auction_concept_analysis import SKIP_CONCEPTS

        # 过滤业绩/股权/国资等杂标签，仅保留可交易的题材概念
        _ladder_skip = {
            "中报预增", "半年报预增", "中报增长", "半年报增长", "中报扭亏", "中报减亏",
            "半年报预计扭亏", "年报预增", "季报预增", "预盈预增", "业绩预增", "业绩增长",
            "业绩改善", "亏损收窄", "预增",
            "国企改革", "央企改革", "央企国企改革", "国资改革", "混改",
            "股权转让(并购重组)", "并购重组", "股权转让", "重组概念",
            "举牌", "定增", "增持", "减持", "回购", "股权激励", "员工持股",
        }

        def _is_generic_concept(c: str) -> bool:
            return c in _ladder_skip or c in SKIP_CONCEPTS or c.endswith("国资")

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
            # 问财列名存在别名且不带/带变动后缀，用健壮匹配
            first_time = _iwencai_first_match(row, "首次封板时间", "最新首次涨停时间")
            seal_amt_str = _iwencai_first_match(row, "封单额", "隔夜单额")
            open_times_str = _iwencai_first_match(row, "炸板次数", "涨停开板次数")

            concepts = (
                [c.strip() for c in reason.split("+") if c.strip() and not _is_generic_concept(c.strip())]
                if reason
                else []
            )

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
                seal_amount = _parse_cn_amount(seal_amt_str)
            except (ValueError, TypeError):
                seal_amount = 0
            try:
                open_times = int(float(open_times_str))
            except (ValueError, TypeError):
                open_times = 0
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
                "first_seal_time": first_time,
                "seal_amount": seal_amount,
                "open_times": open_times,
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

        summary = f"共 {total} 只涨停，首板 {first} 只，连板 {cont} 只，最高 {max_b} 板"
        if from_path.startswith("fallback:"):
            summary += f"（暂无今日数据，展示最近交易日 " + from_path.split(":")[1] + "）"

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
            "summary": summary,
        }

        # Write cache（仅今日数据写缓存；回退数据不覆盖今天的缓存）
        if not from_path.startswith("fallback:"):
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
        from strategies.ict.ict_indicators import (
            smc_pipeline, swing_points, calc_bos_choch,
            calc_order_blocks, calc_fvg, calc_liquidity_sweep,
            detect_3_1_structure, calc_ote, calc_trend_continuous
        )
    except ImportError as e:
        return _err(f"ict_indicators不可用: {e}")

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

        # 多周期趋势分离（展示层，不影响回测核心）
        # 主结构（HTF）：保留原始 swing_major 判定
        trend_major = trend
        # 短线状态（LTF）：MA5/MA20 排列 + 价格位置
        ma5 = float(last_row.get("ma5", 0)) if pd.notna(last_row.get("ma5")) else 0
        if ma5 > ma20 and last_close > ma20:
            trend_recent = 1
        elif ma5 < ma20 and last_close < ma20:
            trend_recent = -1
        else:
            trend_recent = 0
        # 日线前高（分水岭），用于解释
        major_sh = result[result["swing_major"] == 1]
        prev_high = round(float(major_sh["high"].max()), 2) if not major_sh.empty else None

        # 近期信号统计
        recent_signals = signals[-5:] if len(signals) >= 5 else signals
        recent_bull_bos = sum(1 for s in signals[-10:] if s["type"] == "BOS" and s["direction"] == "bullish")
        recent_bear_bos = sum(1 for s in signals[-10:] if s["type"] == "BOS" and s["direction"] == "bearish")
        recent_bull_choch = sum(1 for s in signals[-10:] if s["type"] == "ChoCH" and s["direction"] == "bullish")
        recent_bear_choch = sum(1 for s in signals[-10:] if s["type"] == "ChoCH" and s["direction"] == "bearish")

        # 分析建议
        analysis_parts = []
        if trend_major > 0:
            analysis_parts.append("日线主结构偏多（HH/HL结构）")
        elif trend_major < 0:
            htf_text = "，前高 {} 未突破".format(prev_high) if prev_high else ""
            analysis_parts.append("日线主结构偏空（LH/LL结构）{}".format(htf_text))
        else:
            analysis_parts.append("日线主结构不明朗，处于震荡区间")

        if trend_recent > 0:
            analysis_parts.append("短线 MA5 站上 MA20 且价格站上 MA20，处于反弹/偏多状态")
        elif trend_recent < 0:
            analysis_parts.append("短线 MA5 跌破 MA20 且价格跌破 MA20，处于走弱状态")
        else:
            analysis_parts.append("短线围绕 MA20 震荡，方向不明")

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
            analysis_parts.append(f"近期多头BOS({recent_bull_bos}次)多于空头BOS({recent_bear_bos}次)，短线多头信号活跃")
        elif recent_bear_bos > recent_bull_bos:
            analysis_parts.append(f"近期空头BOS({recent_bear_bos}次)多于多头BOS({recent_bull_bos}次)，短线空头信号活跃")

        if fvg_zones:
            last_fvg = fvg_zones[-1]
            fvg_bottom = last_fvg["bottom"]
            fvg_top = last_fvg["top"]
            if last_fvg["type"] == "bullish":
                if fvg_bottom <= last_close <= fvg_top:
                    analysis_parts.append(f"价格在看涨FVG区间内({fvg_bottom:.2f}-{fvg_top:.2f})，存在支撑")
                elif last_close > fvg_top:
                    analysis_parts.append(f"价格已突破看涨FVG上沿({fvg_top:.2f})，脱离支撑区，注意回踩")
                else:
                    analysis_parts.append(f"价格跌破看涨FVG({fvg_bottom:.2f}-{fvg_top:.2f})，支撑失效")
            elif last_fvg["type"] == "bearish":
                if fvg_bottom <= last_close <= fvg_top:
                    analysis_parts.append(f"价格在看跌FVG区间内({fvg_bottom:.2f}-{fvg_top:.2f})，存在压力")
                elif last_close > fvg_top:
                    analysis_parts.append(f"价格突破看跌FVG上沿({fvg_top:.2f})，压力失效")
                else:
                    analysis_parts.append(f"价格位于看跌FVG下方({fvg_bottom:.2f}-{fvg_top:.2f})，远离压力区")

        if ob_zones:
            last_ob = ob_zones[-1]
            if last_close >= last_ob["bottom"] and last_close <= last_ob["top"]:
                analysis_parts.append(f"价格在订单块(OB)区间内({last_ob['bottom']:.2f}-{last_ob['top']:.2f})，机构关注区域")
            elif last_close < last_ob["bottom"]:
                analysis_parts.append(f"价格跌破订单块下沿({last_ob['bottom']:.2f})，OB支撑失效")
            else:
                analysis_parts.append(f"价格位于订单块上方，原压力区({last_ob['bottom']:.2f}-{last_ob['top']:.2f})已转为潜在支撑")

        # 综合建议：主结构 + 短线状态 + 共振
        if trend_recent > 0 and trend_major > 0:
            suggestion = "主结构与短线共振偏多，关注回踩 MA20 或 OB/FVG 支撑的做多机会"
        elif trend_recent > 0 and trend_major < 0:
            prev_hint = "，突破前高 {} 再看趋势反转".format(prev_high) if prev_high else ""
            suggestion = "日线主结构偏空，但短线已站上 MA20 反弹；可依托 MA20 低吸/做 T{}".format(prev_hint)
        elif trend_recent > 0 and trend_major == 0:
            suggestion = "短线偏多反弹，但日线主结构尚未明朗，轻仓参与或观望"
        elif trend_recent < 0 and trend_major > 0:
            suggestion = "主结构偏多但短线走弱，等待回调至 MA20 或 OB/FVG 支撑企稳"
        elif trend_recent < 0 and trend_major < 0:
            if recent_bull_bos > recent_bear_bos:
                suggestion = "主结构与短线共振偏空，但近期有短线 BOS 异动，暂观望"
            else:
                suggestion = "主结构与短线共振偏空，观望为主，等待止跌信号"
        elif trend_recent < 0 and trend_major == 0:
            suggestion = "短线走弱，主结构不明朗，观望等待方向选择"
        elif rsi > 70:
            suggestion = "RSI 超买，短线注意回调风险"
        elif rsi < 30:
            suggestion = "RSI 超卖，可能存在反弹机会，但需等待结构确认"
        else:
            suggestion = "短线方向不明，建议观望等待方向选择"

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
                "trend": trend_recent,
                "trend_major": trend_major,
                "prev_high": prev_high,
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
 
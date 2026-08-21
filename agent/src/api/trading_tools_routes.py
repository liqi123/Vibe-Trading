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
    """Return expectation state for all positions, with live prev_close from DB."""
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

            # 优先从auction表获取prev_close（更及时）,表不存在则回退daily_kline
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
    """Update E price, X price, runaway price, name, and suggestion for a stock."""
    code = data.get("code", "").strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Code required")

    state = _read_json(_PAPER_DIR / "expectation_state.json")
    positions = state.get("positions", [])

    for p in positions:
        if p.get("code") == code:
            if "e_price" in data:
                p["e_price"] = data.get("e_price", 0)
            if "x_price" in data:
                p["x_price"] = data.get("x_price", 0)
            if "runaway_price" in data:
                p["runaway_price"] = data.get("runaway_price", 0)
            if "name" in data:
                p["name"] = data.get("name", "")
            if "suggestion" in data:
                p["suggestion"] = data.get("suggestion", "")
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
            # 竞价时段腾讯 fields[37]=amount 单位是"万元"；统一存储为"元"
            amount = round(basic["amount"] * 10000, 2)
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


def _is_limit_up(code: str, price: float, prev_close: float) -> bool:
    """Check if price is at limit-up (涨停) for the given stock."""
    if prev_close <= 0 or price <= 0:
        return False
    ratio = price / prev_close
    if code.startswith("300") or code.startswith("301") or code.startswith("688"):
        return ratio >= 1.198
    if code.startswith("8"):
        return ratio >= 1.298
    return ratio >= 1.098


def _limit_pct(code: str) -> float:
    """Return the limit-up percentage for the given stock code."""
    if code.startswith("300") or code.startswith("301") or code.startswith("688"):
        return 19.8
    if code.startswith("8"):
        return 29.8
    return 9.8


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
        # date2 → integer format for daily_kline
        d2_int = int(date2.replace("-", ""))
        
        # Find previous trading day before date2
        cur.execute(
            "SELECT MAX(trade_date) FROM daily_kline WHERE trade_date < ?",
            (d2_int,),
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
            "JOIN daily_kline p ON c.code = p.code AND p.trade_date = ? "
            "WHERE c.trade_date = ? AND p.close > 0",
            (prev_trade_date, d2_int),
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
            if _is_limit_up(code, info["price"], info["prev_close"]):
                today_limitup_codes.add(code)

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
            }

        all_codes = prev_limitup_codes | today_limitup_codes
        both = [build_stock(c) for c in sorted(prev_limitup_codes & today_limitup_codes)]
        prev_only = [build_stock(c) for c in sorted(prev_limitup_codes - today_limitup_codes)]
        today_only = [build_stock(c) for c in sorted(today_limitup_codes - prev_limitup_codes)]

        both.sort(key=lambda x: x["vol_today"], reverse=True)
        prev_only.sort(key=lambda x: x["vol_today"], reverse=True)
        today_only.sort(key=lambda x: x["vol_today"], reverse=True)
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
        # 先按最宽门槛拉候选（创业板/科创板上限10%），Python层按板块二次过滤
        sql_max = max(max_chg, 10.0)
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

        # 板块区分：创业板(300/301)、科创板(688) 20cm 上限 10%；主板(其他) 10cm 上限 9%
        def _board_max_chg(code: str) -> float:
            bare = code[2:] if code.startswith(("sh", "sz", "bj")) else code
            if bare.startswith(("300", "301", "688")):
                return 10.0
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
                "auction_amount_wan": round(auction_amount / 10000, 0) if auction_amount else 0,
                "prev_auction_vol": prev_vol,
                "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
                "prev_high": prev_high,
                "gap_break_prev_high": gap_break_prev_high,
            })

        # 给每只股票匹配同花顺行业板块（L2），并按行业板块当日涨幅倒序
        try:
            import csv as _csv
            from pathlib import Path as _Path
            # 1) 加载同花顺行业列表（L2 名称 -> 881xxx 代码）
            ths_csv = _Path(__file__).resolve().parents[4] / "data" / "market_sentiment" / "ths_industry_codes.csv"
            name_to_code: dict[str, str] = {}
            if ths_csv.exists():
                with ths_csv.open(encoding="utf-8-sig", newline="") as f:
                    for row in _csv.DictReader(f):
                        nm, cd = (row.get("name") or "").strip(), (row.get("code") or "").strip()
                        if nm and cd:
                            name_to_code[nm] = cd

            # 2) 裸代码 -> 带前缀代码（用于 stock_ths_industry 查询）
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
            # 3) 查询每只股票的同花顺行业 L2
            ind_rows = cur.execute(
                f"SELECT code, industry_l2 FROM stock_ths_industry WHERE code IN ({placeholders})",
                prefixed,
            ).fetchall()
            code_to_l2 = {r[0]: r[1] for r in ind_rows if r[1]}

            # 4) 查询当日所有 sh881xxx 行业指数的涨跌幅；当日缺失则回退最近交易日
            today_val = int(date.replace("-", "")) if is_int else date
            ind_idx_rows = cur.execute(
                f"SELECT code, close FROM daily_kline WHERE {date_col}=? AND code LIKE 'sh881%'",
                (today_val,),
            ).fetchall()
            if not ind_idx_rows:
                fb = cur.execute(
                    f"SELECT MAX({date_col}) FROM daily_kline WHERE code LIKE 'sh881%'"
                ).fetchone()
                if fb and fb[0]:
                    today_val = fb[0]
                    ind_idx_rows = cur.execute(
                        f"SELECT code, close FROM daily_kline WHERE {date_col}=? AND code LIKE 'sh881%'",
                        (today_val,),
                    ).fetchall()
            today_close = {r[0]: r[1] for r in ind_idx_rows}
            # 前一交易日
            prev_td_val = int(prev_date.replace("-", "")) if (prev_date and is_int) else prev_date
            if not prev_td_val:
                # 当 prev_date 缺失，回退 today_val 的前一交易日
                pv = cur.execute(
                    f"SELECT MAX({date_col}) FROM daily_kline WHERE code LIKE 'sh881%' AND {date_col} < ?",
                    (today_val,),
                ).fetchone()
                if pv and pv[0]:
                    prev_td_val = pv[0]
            prev_close = {}
            if prev_td_val:
                prev_rows = cur.execute(
                    f"SELECT code, close FROM daily_kline WHERE {date_col}=? AND code LIKE 'sh881%'",
                    (prev_td_val,),
                ).fetchall()
                prev_close = {r[0]: r[1] for r in prev_rows}

            # 5) 行业 L2 名称 -> 当日涨幅
            industry_chg: dict[str, float] = {}
            for nm, cd in name_to_code.items():
                tc, pc = today_close.get(f"sh{cd}"), prev_close.get(f"sh{cd}")
                if tc and pc and pc > 0:
                    industry_chg[nm] = round((tc / pc - 1) * 100, 2)

            # 6) 给每只股票挂 top_industry / top_industry_chg
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


@router.post("/auction/ai-analysis")
def auction_ai_analysis(data: dict) -> dict:
    """AI 竞价分析：汇总当日竞价数据，调用 LLM 生成分析报告。

    Body: { "date": "YYYY-MM-DD", "concept_source": "industry|concept" }
    """
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
            # 今日竞价涨停数
            cur.execute(
                "SELECT code, name, auction_price, prev_close FROM auction WHERE date=? AND prev_close>0 AND auction_price/prev_close >= 1.095",
                (date_str,),
            )
            today_lu = cur.fetchall()
            # 昨日涨停今日竞价
            cur.execute("SELECT DISTINCT date FROM auction WHERE date < ? ORDER BY date DESC LIMIT 1", (date_str,))
            prev_row = cur.fetchone()
            prev_lu = []
            if prev_row:
                prev_date = prev_row[0]
                cur.execute(
                    "SELECT code, name, auction_price, prev_close FROM auction WHERE date=? AND prev_close>0 AND auction_price/prev_close >= 1.095",
                    (prev_date,),
                )
                prev_lu = cur.fetchall()
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
                    # auction_amount 单位为万元（DB中值≈万级别）
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

    if len(sections) <= 1:
        return {"error": f"日期 {date_str} 无竞价数据可分析"}

    summary = "\n\n".join(sections)

    # 2) 调用 LLM
    try:
        try:
            from dotenv import load_dotenv
            load_dotenv(_PROJECT_ROOT / ".env")
        except ImportError:
            pass

        from analysis.llm_analyzer import call_llm

        auction_system = (
            "你是 A 股短线竞价分析师，擅长从集合竞价数据中捕捉情绪、板块联动和量能异动。\n"
            "分析要求：\n"
            "1. 横向对比：把多只股票放一起看，找出谁超预期、谁低于预期、谁在异动，不要逐只孤立点评\n"
            "2. 模式识别：竞价涨幅+量比+位置标签的组合要结合起来解读，例如『放量突破压力』和『缩量贴近支撑』是两种完全不同的信号\n"
            "3. 具体到数字：点评要引用具体数据（如『竞价+7%且量较昨日2.9倍』），不要空泛地说『量能放大』\n"
            "4. 给出判断而非复述：不要重复语料里已有的标签，要给出你的独立判断（是否符合预期、是机会还是风险、建议动作）\n"
            "5. 简洁有重点：每只股票1-2句话点透，避免套话模板\n"
            "6. 风险第一：高位放量、跌破支撑等危险信号要明确提示"
        )

        prompt = (
            f"以下是今天 A 股集合竞价的数据摘要：\n\n{summary}\n\n"
            "请用中文做一段竞价分析报告，结构如下：\n"
            "1. **竞价整体情绪**（红盘率/涨停数/量能变化，一句话定性）\n"
            "2. **热点板块解读**（最强板块的锚点/中军/弹性标的，结合竞价数据判断强度）\n"
            "3. **重点个股关注**（竞价量异常/连续涨停/超预期标的，从全市场角度挑）\n"
            "4. **自选股诊断**（重点：不要逐只复述数据，要做横向对比——谁最强、谁最弱、谁超预期、谁需要警惕；"
            "每只结合『竞价涨幅+量比+支撑压力位置』给出独立判断和具体操作建议）\n"
            "5. **操作思路**（接力方向/回避方向/风险提示）\n\n"
            "注意：只做客观数据分析与多视角推演，不保证结果，不构成投资建议。"
        )
        report = call_llm(prompt, model="mimo-v2.5-pro", system_prompt=auction_system)
        return {"report": report, "date": date_str, "summary": summary}
    except Exception as e:
        detail = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                detail += " | body=" + str(resp.text[:500])
            except Exception:
                pass
        _log.warning("auction AI analysis failed: %s", detail)
        return {"error": detail}


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

        from analysis.external.iwencai import query_data

        raw = query_data(
            "今日涨停股票 剔除ST 剔除退市 股票代码 股票简称 收盘价 最新涨跌幅 连续涨停天数 涨停原因 成交额"
        )
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
 
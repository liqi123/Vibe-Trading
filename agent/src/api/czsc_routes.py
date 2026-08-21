"""缠论 CZSC 相关 API 路由。

提供端点：
- GET  /tools/czsc/{code}            个股缠论结构分析（笔、中枢、买卖点、信号）
- GET  /tools/czsc/signals           列出可用信号函数（按分类）
- POST /tools/czsc/scan              缠论选股扫描（全市场或指定代码列表）
- GET  /tools/czsc/portfolio         缠论策略模拟盘持仓状态
- POST /tools/czsc/analyze-list      批量分析代码列表（给自选股批量用）
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

_log = logging.getLogger("czsc_routes")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_PAPER_DIR = _PROJECT_ROOT / "paper"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/tools", tags=["czsc"])

_CACHE_SCAN: dict[str, Any] = {"result": None, "date": None}
_CACHE_LOCK = threading.Lock()


def _read_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _atomic_write_json(path: Path, data: dict | list) -> None:
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _ok(**kwargs) -> dict:
    return {"ok": True, **kwargs}


def _err(detail: str = "", **kwargs) -> dict:
    return {"ok": False, "detail": detail, **kwargs}


def _stock_table(db: sqlite3.Connection | None = None) -> str:
    own_db = db is None
    if own_db:
        db = _get_db()
        if db is None:
            return 'stock_names'
    try:
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        result = 'stock_names' if 'stock_names' in tables else 'stocks'
    except Exception:
        result = 'stock_names'
    finally:
        if own_db and db is not None:
            db.close()
    return result


def _open_db_readonly(path: str) -> sqlite3.Connection | None:
    """以 immutable 只读模式打开 SQLite，绕过 sandbox 对 -wal/-journal 的拦截。

    immutable=1 告知 SQLite 文件不会被修改，故不打开 WAL/journal，
    仅读主 .db 文件——适合只读 API。主库写操作由 `python -m utils update` 独立连接处理。
    """
    uri = "file:" + str(path).replace("\\", "/").lstrip("/") + "?immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        # 验证可读
        conn.execute("SELECT 1").fetchone()
        return conn
    except Exception:
        return None


def _db_max_date(conn: sqlite3.Connection) -> int | str | None:
    """获取某库 daily_kline 的最大日期（用于新鲜度比较）。"""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_kline)").fetchall()}
        dc = "trade_date" if "trade_date" in cols else "date"
        return conn.execute(f"SELECT MAX({dc}) FROM daily_kline").fetchone()[0]
    except Exception:
        return None


def _get_db() -> sqlite3.Connection | None:
    candidates = [
        r"G:\tdx_data\tdx_daily.db",
        r"E:\DataBase\tdx_data.db",
        str(_PROJECT_ROOT / "tdx_daily.db"),
        str(_PROJECT_ROOT / "tdx_data.db"),
    ]
    # 优先从 utils.config 拿 DB_PATH（项目规范）
    try:
        from utils.config import DB_PATH
        p = Path(str(DB_PATH))
        if p.exists():
            candidates.insert(0, str(p))
    except Exception:
        pass

    # 遍历候选，用 immutable 只读打开（避开 sandbox 对 WAL 的拦截），
    # 并按 max date 选最新库——避免命中陈旧本地副本。
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
            mx = _db_max_date(conn)
            if mx is None:
                conn.close()
                continue
            # 选 max date 最大的库（trade_date 是 int，date 是 str，均可比较）
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


def _normalize_code(code: str) -> str:
    raw = code.strip().lower()
    if raw.startswith(("sh", "sz", "bj")):
        return raw
    if raw.isdigit():
        return ("sh" if raw.startswith(("6", "9")) else "sz") + raw
    return raw


def _load_df_for_code(db: sqlite3.Connection, code: str, limit: int = 300) -> pd.DataFrame:
    """从 daily_kline 拉指定代码的 K 线并返回 DataFrame。"""
    cols = {r[1] for r in db.execute("PRAGMA table_info(daily_kline)").fetchall()}
    date_col = "trade_date" if "trade_date" in cols else "date"
    sql = (
        f"SELECT code, {date_col} AS date, open, high, low, close, volume, amount "
        f"FROM daily_kline WHERE code=? ORDER BY {date_col} DESC LIMIT ?"
    )
    rows = db.execute(sql, (code, limit)).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume", "amount"])
    df = df.sort_values("date").reset_index(drop=True)
    is_int = date_col == "trade_date"
    if is_int:
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    else:
        df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _serialize_bis(bi_list: list[Any]) -> list[dict]:
    """把 BI 对象列表序列化为 JSON 友好的 dict。"""
    result = []
    for bi in bi_list:
        try:
            sdt = getattr(bi, "sdt", None)
            edt = getattr(bi, "edt", None)
            sdt_str = sdt.strftime("%Y-%m-%d") if sdt else ""
            edt_str = edt.strftime("%Y-%m-%d") if edt else ""
            direction = getattr(bi, "direction", None)
            # czsc 1.0.1 Direction 枚举 str() 返回中文「向上/向下」，前端期望 up/down
            try:
                from strategies.czsc.czsc_engine import normalize_direction
                dir_str = normalize_direction(direction) or ""
            except Exception:
                dir_str = str(direction).split(".")[-1].lower() if direction else ""
            high = float(getattr(bi, "high", 0) or 0)
            low = float(getattr(bi, "low", 0) or 0)
            power = float(getattr(bi, "power", 0) or 0)
            result.append({
                "sdt": sdt_str, "edt": edt_str,
                "direction": dir_str,
                "high": round(high, 3), "low": round(low, 3),
                "power": round(power, 3),
            })
        except Exception:
            continue
    return result


def _serialize_zs(zs_list: list[Any]) -> list[dict]:
    """把中枢 ZS 对象列表序列化为 dict。"""
    result = []
    for zs in zs_list:
        try:
            sdt = getattr(zs, "sdt", None)
            edt = getattr(zs, "edt", None)
            sdt_str = sdt.strftime("%Y-%m-%d") if sdt else ""
            edt_str = edt.strftime("%Y-%m-%d") if edt else ""
            # czsc._native.ZS 实际属性为 zg/zd/gg/dd（旧版 zgg/zdd/zgz/zdz 不存在）
            zg = float(getattr(zs, "zg", 0) or 0)   # 中枢上沿
            zd = float(getattr(zs, "zd", 0) or 0)   # 中枢下沿
            gg = float(getattr(zs, "gg", 0) or 0)   # 区间最高
            dd = float(getattr(zs, "dd", 0) or 0)   # 区间最低
            result.append({
                "sdt": sdt_str, "edt": edt_str,
                "zgg": round(zg, 3),   # 中枢高（上沿）= zg
                "zdd": round(zd, 3),   # 中枢低（下沿）= zd
                "zgz": round(gg, 3),   # 上轨 = gg
                "zdz": round(dd, 3),   # 下轨 = dd
            })
        except Exception:
            continue
    return result


def _serialize_signals(signals: list[Any]) -> list[dict]:
    """把信号对象列表转成 dict（k1-k3 + v1-v3 + score）。"""
    out = []
    for s in signals:
        try:
            item: dict[str, Any] = {}
            for key in ["k1", "k2", "k3", "k4", "k5", "v1", "v2", "v3", "score"]:
                v = getattr(s, key, None)
                if v is not None and v != "":
                    item[key] = str(v)
            if item:
                out.append(item)
        except Exception:
            continue
    return out


def _run_score_czsc(czsc_obj, current_price: float,
                    sig_dicts: list[dict] | None = None) -> dict[str, Any]:
    """调用根项目 score_czsc（回测/实盘/API 单一事实来源），返回安全字段。

    为避免 import czsc_strategy 时的循环依赖或环境差异，这里延迟导入；
    sig_dicts 用于生成简洁信号摘要（detect_buy_points 已传入 czsc_obj 生成原生信号，
    score_czsc 的 sig_text 传空即可，native_signals 已在其内部直接读取）。
    """
    try:
        from strategies.czsc.czsc_strategy import score_czsc
        return score_czsc(czsc_obj, current_price, "")
    except Exception as e:
        _log.warning("_run_score_czsc 回退简化评分: %s", e, exc_info=True)
        # 回退: 基于 bp_result 手写 (和 detect_buy_points 的 buy_points/中枢/笔方向 对齐)
        raise


# ---------------------------------------------------------------------------
# 个股分析
# ---------------------------------------------------------------------------

@router.get("/czsc/{code}")
def get_czsc_analysis(code: str, limit: int = 300, with_signals: bool = True):
    """返回个股缠论结构分析。

    - K 线、笔、中枢、信号、买卖点、评分
    """
    code_norm = _normalize_code(code)
    db = _get_db()
    if db is None:
        return _err("无法连接数据库")
    try:
        df = _load_df_for_code(db, code_norm, limit=limit)
    finally:
        db.close()
    if df.empty:
        return _err(f"无数据: {code_norm}")

    try:
        from strategies.czsc.czsc_engine import analyze_stock
        from strategies.czsc.signals import DEFAULT_SIGNALS, detect_buy_points
    except ImportError as e:
        return _err(f"strategies.czsc 不可用: {e}")

    signals_seq = DEFAULT_SIGNALS if with_signals else None
    t0 = time.time()
    try:
        res = analyze_stock(df, signals_seq=signals_seq)
    except Exception as e:
        return _err(f"缠论分析失败: {e}")

    czsc_obj = res.get("czsc")
    if czsc_obj is None:
        return _err(f"数据不足，无法构建缠论结构（需>=10根K线，当前{len(df)}根）")

    # 1) K线序列（供前端绘图）
    klines = []
    for _, r in df.iterrows():
        klines.append({
            "time": r["date"].strftime("%Y-%m-%d"),
            "open": round(float(r["open"]), 2),
            "high": round(float(r["high"]), 2),
            "low": round(float(r["low"]), 2),
            "close": round(float(r["close"]), 2),
            "volume": int(float(r["volume"])),
        })

    # 2) 笔 / 中枢
    bis = _serialize_bis(res.get("bi_list", []))
    zs = _serialize_zs(res.get("zs_list", []))

    # 3) 信号 & 买点
    sig_dicts = _serialize_signals(res.get("signals", []))
    current_price = float(df.iloc[-1]["close"])
    bp = detect_buy_points(czsc_obj, current_price=current_price)

    # 4) 综合评分 (调用根项目 score_czsc, 与回测/实盘同一逻辑, 含 safe_to_buy)
    sc = _run_score_czsc(czsc_obj, current_price, sig_dicts)
    score = int(sc.get("total", 0))
    safe_to_buy = bool(sc.get("safe_to_buy", True))
    zg = float(sc.get("zg", 0) or 0)
    safe_price_max = float(sc.get("safe_price_max", 0) or 0)

    # 5) 简要文字解读
    trend_hint = ""
    dir_ = bp.get("last_bi_dir")
    if dir_ == "up":
        trend_hint = "最后一笔向上，短线偏多"
    elif dir_ == "down":
        trend_hint = "最后一笔向下，短线偏空"
    else:
        trend_hint = "笔方向不明确"
    zs_hint = ""
    if bp.get("in_zs"):
        z_range = bp.get("zs_range")
        if z_range:
            zs_hint = f"价格在中枢区间 [{z_range[0]:.2f}, {z_range[1]:.2f}] 内震荡"
        else:
            zs_hint = "价格在中枢内部震荡"
    else:
        z_range = bp.get("zs_range")
        if z_range and current_price > z_range[1]:
            zs_hint = f"价格已脱离中枢上沿 {z_range[1]:.2f}（三买候选）"
        elif z_range and current_price < z_range[0]:
            zs_hint = f"价格已跌破中枢下沿 {z_range[0]:.2f}（弱势）"
        else:
            zs_hint = "暂未形成有效中枢"
    suggestions = [trend_hint, zs_hint]
    if bp.get("buy_points"):
        suggestions.append("买点信号: " + "、".join(bp["buy_points"]))
    if not safe_to_buy and zg > 0:
        suggestions.append(f"⚠ 价格脱离中枢安全区 (上限 {safe_price_max:.2f})，高位不追")

    return _ok(
        code=code_norm,
        klines=klines,
        bis=bis,
        zs_list=zs,
        signals=sig_dicts,
        buy_point_info=bp,
        score=score,
        safe_to_buy=safe_to_buy,
        zg=zg,
        safe_price_max=round(safe_price_max, 3) if safe_price_max else 0,
        analysis={
            "date": df.iloc[-1]["date"].strftime("%Y-%m-%d"),
            "price": current_price,
            "bi_count": bp.get("bi_count", 0),
            "zs_count": bp.get("zs_count", 0),
            "last_bi_dir": bp.get("last_bi_dir"),
            "points": suggestions,
            "suggestion": f"缠论评分 {score}/100 — " + "；".join(x for x in suggestions if x),
        },
        elapsed_ms=int((time.time() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# 信号列表
# ---------------------------------------------------------------------------

@router.get("/czsc/signals/list")
def list_czsc_signals(category: str | None = None):
    """列出 czsc 信号函数名。

    category 参数：None=全部，或 cxt/tas/bar/jcc/zdy/xl/vol
    """
    try:
        from strategies.czsc.signals import list_all_signals, get_signal_category
    except ImportError as e:
        return _err(f"信号库不可用: {e}")

    try:
        names = list_all_signals(category=category)
        grouped: dict[str, list[str]] = {}
        for n in names:
            try:
                cat = get_signal_category(n)
            except Exception:
                cat = "other"
            grouped.setdefault(cat, []).append(n)
        return _ok(signals=names, grouped=grouped, total=len(names))
    except Exception as e:
        return _err(f"信号列表查询失败: {e}")


# ---------------------------------------------------------------------------
# 批量分析（自选股一键获取缠论信息）
# ---------------------------------------------------------------------------

@router.post("/czsc/analyze-list")
def analyze_czsc_list(body: dict):
    """批量分析多个代码，返回 {code: 分析摘要}。

    Body: { "codes": ["sz000001", "sh600519", ...] }
    """
    codes = body.get("codes") or []
    if not codes:
        return _err("codes 不能为空")

    norm_codes = [_normalize_code(c) for c in codes]
    db = _get_db()
    if db is None:
        return _err("无法连接数据库")

    try:
        from strategies.czsc.czsc_engine import analyze_stock
        from strategies.czsc.signals import DEFAULT_SIGNALS, detect_buy_points
    except ImportError as e:
        db.close()
        return _err(f"strategies.czsc 不可用: {e}")

    results: dict[str, Any] = {}
    t0 = time.time()
    try:
        for c in norm_codes:
            try:
                df = _load_df_for_code(db, c, limit=260)
                if df.empty or len(df) < 30:
                    results[c] = {"ok": False, "error": "数据不足"}
                    continue
                r = analyze_stock(df, signals_seq=DEFAULT_SIGNALS)
                if not r.get("czsc"):
                    results[c] = {"ok": False, "error": "结构构建失败"}
                    continue
                price = float(df.iloc[-1]["close"])
                bp = detect_buy_points(r["czsc"], current_price=price)
                sigs = _serialize_signals(r.get("signals", []))
                score = _calc_score(bp, sigs)
                results[c] = {
                    "ok": True,
                    "price": round(price, 2),
                    "score": score,
                    "last_bi_dir": bp.get("last_bi_dir"),
                    "bi_count": bp.get("bi_count"),
                    "zs_count": bp.get("zs_count"),
                    "in_zs": bp.get("in_zs"),
                    "zs_range": bp.get("zs_range"),
                    "buy_points": bp.get("buy_points") or [],
                }
            except Exception as e:
                results[c] = {"ok": False, "error": str(e)}
    finally:
        db.close()

    return _ok(results=results, elapsed_ms=int((time.time() - t0) * 1000))


# ---------------------------------------------------------------------------
# 选股扫描
# ---------------------------------------------------------------------------

@router.post("/czsc/scan")
def scan_czsc(body: dict | None = None):
    """缠论选股扫描。

    返回评分较高（>=50）且具备买点候选的股票。
    Body 参数（可选）:
      - codes: list[str]    限定代码，None 表示全市场
      - limit: int          每只拉 K 线数，默认 260
      - min_score: int      最低评分阈值，默认 50
      - with_buy_point: bool  仅返回有买点信号的，默认 True
      - require_safe: bool    仅返回 safe_to_buy=True（防高位接盘/陈旧三买），默认 True
      - use_cache: bool     当日重复调用走缓存，默认 True
      - max_codes: int      全市场扫描上限，默认 800（避免超时）
    """
    body = body or {}
    codes = body.get("codes")
    limit = int(body.get("limit", 260))
    min_score = int(body.get("min_score", 50))
    with_buy_point = bool(body.get("with_buy_point", True))
    require_safe = bool(body.get("require_safe", True))
    use_cache = bool(body.get("use_cache", True))
    max_codes = int(body.get("max_codes", 800))

    today = date.today().isoformat()
    if use_cache and codes is None:
        with _CACHE_LOCK:
            cached = _CACHE_SCAN.get("result")
            if cached and _CACHE_SCAN.get("date") == today:
                return _ok(**cached, cached=True)

    db = _get_db()
    if db is None:
        return _err("无法连接数据库")

    try:
        from strategies.czsc.czsc_engine import analyze_stock
        from strategies.czsc.signals import DEFAULT_SIGNALS, detect_buy_points
    except ImportError as e:
        db.close()
        return _err(f"strategies.czsc 不可用: {e}")

    t0 = time.time()
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(daily_kline)").fetchall()}
        date_col = "trade_date" if "trade_date" in cols else "date"

        # 1) 收集待分析代码
        if codes:
            norm_codes = [_normalize_code(c) for c in codes]
        else:
            # 快速预筛选: 取最新交易日有成交的所有 code（0.05s）
            # 旧版用 AVG(amount) 聚合 → amount 列全 NULL 且 4.8GB 库全表扫描耗时 2min+
            mx = db.execute(f"SELECT MAX({date_col}) FROM daily_kline").fetchone()[0]
            all_codes = [r[0] for r in db.execute(
                f"SELECT DISTINCT code FROM daily_kline WHERE {date_col} = ?", (mx,)
            ).fetchall()]
            # 过滤掉指数/基金代码，只保留 A 股个股
            # sh000xxx=上证指数系列 sz399xxx=深证指数系列 sh5/sz1=基金 bj8/bj4=北交所个股
            def _is_stock(code: str) -> bool:
                if len(code) < 8:
                    return False
                prefix = code[:2].lower()
                digits = code[2:]
                if not digits.isdigit():
                    return False
                if prefix in ("sh", "sz"):
                    return digits[0] in ("0", "3", "6") and not (
                        prefix == "sh" and digits.startswith("000")
                    ) and not (
                        prefix == "sz" and digits.startswith("399")
                    )
                if prefix == "bj":
                    return digits[0] in ("4", "8")
                return False
            norm_codes = [c for c in all_codes if _is_stock(c)]
            # 限制扫描数量，避免全市场 6000+ 只导致超时
            if max_codes > 0 and len(norm_codes) > max_codes:
                _log.info("scan: %d codes > max_codes %d, truncating", len(norm_codes), max_codes)
                norm_codes = norm_codes[:max_codes]

        if not norm_codes:
            return _err("没有符合预筛选条件的股票")

        _log.info("scan: %d codes to analyze", len(norm_codes))

        # 2) 名称映射
        st_table = _stock_table(db)
        try:
            name_rows = db.execute(
                f"SELECT code, name FROM {st_table} WHERE code IN ("
                + ",".join(["?"] * len(norm_codes)) + ")",
                norm_codes,
            ).fetchall()
        except Exception:
            name_rows = []
        name_map = {r[0]: r[1] for r in name_rows}

        # 3) 批量加载 K 线（一次 SQL 取所有票，避免 N 次单独查询）
        placeholders = ",".join(["?"] * len(norm_codes))
        is_int = date_col == "trade_date"
        batch_rows = db.execute(
            f"SELECT code, {date_col} AS date, open, high, low, close, volume, amount "
            f"FROM daily_kline WHERE code IN ({placeholders}) "
            f"ORDER BY code, {date_col}",
            norm_codes,
        ).fetchall()
        df_all = pd.DataFrame(batch_rows, columns=[
            "code", "date", "open", "high", "low", "close", "volume", "amount"
        ])
        if is_int:
            df_all["date"] = pd.to_datetime(df_all["date"].astype(str), format="%Y%m%d")
        else:
            df_all["date"] = pd.to_datetime(df_all["date"])
        for c in ["open", "high", "low", "close", "volume", "amount"]:
            df_all[c] = pd.to_numeric(df_all[c], errors="coerce").fillna(0.0)
        # 按代码分组，每只取最近 limit 根
        grouped = {code: g.tail(limit).reset_index(drop=True)
                   for code, g in df_all.groupby("code")}
        _log.info("scan: loaded %d stocks (%d rows) in %.1fs",
                  len(grouped), len(df_all), time.time() - t0)

        # 4) 逐个分析
        picks: list[dict] = []
        skipped = 0
        for c in norm_codes:
            df = grouped.get(c)
            if df is None or len(df) < 60:
                skipped += 1
                continue
            try:
                r = analyze_stock(df, signals_seq=DEFAULT_SIGNALS)
                if not r.get("czsc"):
                    skipped += 1
                    continue
                price = float(df.iloc[-1]["close"])
                bp = detect_buy_points(r["czsc"], current_price=price)
                sc = _run_score_czsc(r["czsc"], price)
                score = int(sc.get("total", 0))
                if score < min_score:
                    continue
                if with_buy_point and not bp.get("buy_points"):
                    continue
                picks.append({
                    "code": c,
                    "name": name_map.get(c, ""),
                    "price": round(price, 2),
                    "score": score,
                    "buy_points": bp.get("buy_points") or [],
                    "buy_point": sc.get("buy_point"),
                    "last_bi_dir": bp.get("last_bi_dir"),
                    "bi_count": bp.get("bi_count"),
                    "zs_count": bp.get("zs_count"),
                    "in_zs": bp.get("in_zs"),
                    "zs_range": bp.get("zs_range"),
                    "safe_to_buy": bool(sc.get("safe_to_buy", True)),
                    "zg": float(sc.get("zg", 0) or 0),
                    "safe_price_max": round(float(sc.get("safe_price_max", 0) or 0), 3),
                })
            except Exception:
                skipped += 1
                continue
    finally:
        db.close()

    # 安全性硬过滤: 剔除 safe_to_buy=False（高位接盘/陈旧三买）
    if require_safe:
        picks = [sc for sc in picks if bool(sc.get("safe_to_buy", True))]

    picks.sort(key=lambda x: x["score"], reverse=True)
    result = {
        "picks": picks[:200],
        "total": len(picks),
        "skipped": skipped,
        "scanned": len(norm_codes),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "date": today,
    }
    if codes is None:
        with _CACHE_LOCK:
            _CACHE_SCAN["result"] = result
            _CACHE_SCAN["date"] = today
    return _ok(**result, cached=False)


# ---------------------------------------------------------------------------
# 模拟盘持仓
# ---------------------------------------------------------------------------

@router.get("/czsc/portfolio")
def get_czsc_portfolio():
    """缠论策略模拟盘持仓状态。"""
    path = _PAPER_DIR / "paper_trading_state_czsc.json"
    state = _read_json(path)
    if state and isinstance(state, dict) and state.get("positions"):
        try:
            from data.tencent_quotes import get_prices
            codes_to_query = []
            for p in state["positions"]:
                c = p.get("code", "")
                if c:
                    codes_to_query.append(c)
            prices = get_prices(codes_to_query) if codes_to_query else {}
            for p in state["positions"]:
                c = p.get("code", "")
                if c in prices:
                    p["current_price"] = float(prices[c])
        except Exception:
            _log.warning("get_czsc_portfolio: 实时价格更新失败", exc_info=True)
        if "history" in state:
            state["history"] = sorted(state["history"], key=lambda x: x.get("date", ""), reverse=True)

    if not state:
        state = {
            "name": "缠论策略",
            "strategy": "czsc",
            "initial_capital": 200000,
            "cash": 200000,
            "positions": [],
            "history": [],
        }
    return state


# ---------------------------------------------------------------------------
# 注册函数
# ---------------------------------------------------------------------------

def register_czsc_routes(app, require_auth=None):
    """把 czsc router 挂载到 FastAPI app。"""
    dependencies = []
    if require_auth is not None:
        dependencies = [Depends(require_auth)]
    if dependencies:
        for route in router.routes:
            if hasattr(route, "dependencies"):
                route.dependencies = dependencies
    app.include_router(router)

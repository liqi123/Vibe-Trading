"""另类数据加载器 — 通过问财 API 注入历史截面数据到 Alpha Zoo panel。

所有被封的东财数据（融资融券/资金流/龙虎榜）都走问财替代。
一次调用 = 全区间 × 全市场（5000+ 股票），使用问财 `至` 日期范围语法。

用法:
    from alt_data_loader import load_iwencai_panel
    panel = load_iwencai_panel(universe="all-a-share", period="2026-04-01/2026-07-10")
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger("alt_data_loader")

# ── 问财 API 配置 ────────────────────────────────────────
IWENCAI_KEY = ""
_BASE_URL = "https://openapi.iwencai.com"
_QUERY_URL = f"{_BASE_URL}/v1/query2data"
_SEARCH_URL = f"{_BASE_URL}/v1/comprehensive/search"


def _init_key():
    global IWENCAI_KEY
    if not IWENCAI_KEY:
        IWENCAI_KEY = os.environ.get("VIBE_TRADING_IWENCAI_KEY", "")
        if not IWENCAI_KEY:
            IWENCAI_KEY = os.environ.get("IWENCAI_API_KEY", "")
        if not IWENCAI_KEY:
            env_path = Path(__file__).parents[3] / ".env"
            if env_path.exists():
                try:
                    text = env_path.read_text(encoding="utf-8")
                except Exception:
                    text = env_path.read_text(encoding="gbk")
                for line in text.splitlines():
                    if line.startswith("IWENCAI_API_KEY="):
                        IWENCAI_KEY = line.split("=", 1)[1].strip()
                        break


def _claw_headers(call_type="normal"):
    import secrets
    return {
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": "report-search",
        "X-Claw-Skill-Version": "1.0.0",
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }


def query_iwencai(query: str, max_retries: int = 2) -> list[dict]:
    """问财结构化查询，返回行列表。

    Args:
        query: 查询语句，如 "2026-06-15 换手率 市盈率ttm 融资余额"

    Returns:
        list[dict]: 每行是一只股票，key 是字段名（含日期后缀）
    """
    _init_key()
    if not IWENCAI_KEY:
        log.warning("IWENCAI_API_KEY 未设置")
        return []

    headers = {
        "Authorization": f"Bearer {IWENCAI_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        **_claw_headers("data"),
    }
    payload = {"query": query, "perpage": 5000, "page": 1}

    for attempt in range(max_retries):
        try:
            r = requests.post(_QUERY_URL, json=payload, headers=headers, timeout=(10, 60))
            if r.status_code == 401:
                log.error("iwencai 401 认证失败，请检查 IWENCAI_API_KEY: %s", r.text[:200])
                sys.exit(1)
            if r.status_code != 200:
                log.warning("iwencai HTTP %d: %s", r.status_code, r.text[:200])
                time.sleep(3)
                continue
            data = r.json()
        except Exception as exc:
            log.warning("iwencai request failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(3)
            continue

        # 解析不同返回格式
        if isinstance(data, dict):
            if "datas" in data:
                return data["datas"]
            answer = data.get("data", {}).get("answer")
            if isinstance(answer, list) and answer:
                try:
                    return (answer[0].get("txt", [{}])[0].get("content", {})
                            .get("components", [{}])[0].get("data", {})
                            .get("datas", []))
                except (IndexError, AttributeError):
                    pass
        return []

    log.error("iwencai %d 次重试后仍然失败，停止", max_retries)
    sys.exit(1)


def _stock_code_from_identifier(identifier: str) -> str:
    """'000001.SZ' → '000001', '600519.SH' → '600519'"""
    return identifier.split(".")[0]



def _norm_date(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD"""
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def _parse_range_response(
    rows: list[dict],
    field_maps: dict[str, list[str]],
    all_stock_ids: list[str],
    all_date_strs: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    """解析问财范围查询返回的宽表 → {field_key: {date: {stock: val}}}"""
    import re

    PAT = re.compile(r"^(.+)\[(\d{8})\]$")
    raw_data: dict[str, dict[str, dict[str, float]]] = {}

    # 从第一行发现: field_key → date → column_name 的映射
    first = rows[0]
    col_map: dict[str, dict[str, str]] = {}
    for key in first:
        m = PAT.match(key)
        if not m:
            continue
        raw_field, ds_raw = m.group(1), m.group(2)
        ds = _norm_date(ds_raw)
        if ds not in all_date_strs:
            continue
        for fk, hints in field_maps.items():
            for hint in hints:
                if hint in raw_field or raw_field == hint:
                    col_map.setdefault(fk, {})[ds] = key
                    break
            else:
                continue

    if not col_map:
        log.warning("范围查询: 未匹配到任何字段 (keys=%s)", list(first.keys())[:8])
        return raw_data

    log.info("  解析 %d 字段 × %d 日", len(col_map), max(len(v) for v in col_map.values()))

    for row in rows:
        code = str(row.get("股票代码", ""))
        if not code or "." not in code:
            continue
        parts = code.split(".")
        identifier = f"{parts[0].strip()}.{parts[1].strip().upper()}"
        if identifier not in all_stock_ids:
            continue

        for fk, date_cols in col_map.items():
            for ds, col_name in date_cols.items():
                raw_val = row.get(col_name)
                if raw_val is None:
                    continue
                try:
                    val = float(raw_val)
                except (ValueError, TypeError):
                    continue
                if val == 0 or np.isnan(val) or np.isinf(val):
                    continue
                raw_data.setdefault(fk, {}).setdefault(ds, {})[identifier] = val

    return raw_data


def _parse_single_date_response(
    rows: list[dict],
    field_maps: dict[str, list[str]],
    all_stock_ids: list[str],
) -> dict[str, dict[str, float]]:
    """解析单日问财返回 → {field_key: {stock_id: value}}"""
    result: dict[str, dict[str, float]] = {}

    for row in rows:
        code = str(row.get("股票代码", ""))
        if not code or "." not in code:
            continue
        parts = code.split(".")
        identifier = f"{parts[0].strip()}.{parts[1].strip().upper()}"
        if identifier not in all_stock_ids:
            continue

        for fk, hints in field_maps.items():
            for col_key, col_val in row.items():
                if col_val is None:
                    continue
                matched = any(hint in col_key for hint in hints)
                if not matched:
                    continue
                try:
                    val = float(col_val)
                except (ValueError, TypeError):
                    continue
                if np.isnan(val) or np.isinf(val):
                    continue
                result.setdefault(fk, {})[identifier] = val
                break

    return result


_FUND_DB_PATH: str | None = None


def _get_fund_db_path() -> str:
    global _FUND_DB_PATH
    if _FUND_DB_PATH is None:
        _FUND_DB_PATH = os.environ.get("FUND_DB_PATH") or os.environ.get("TDX_DB_PATH", "")
        if not _FUND_DB_PATH or not Path(_FUND_DB_PATH).exists():
            candidates = [
                r"G:\tdx_data\tdx_daily.db",
                r"E:\DataBase\tdx_data.db",
            ]
            for c in candidates:
                if Path(c).exists():
                    _FUND_DB_PATH = c
                    break
        if not _FUND_DB_PATH:
            _FUND_DB_PATH = ""
    return _FUND_DB_PATH


def _init_fund_table():
    db = _get_fund_db_path()
    if not db:
        return None
    try:
        conn = sqlite3.connect(db, timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fund_daily (
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                turnover_pct REAL,
                pe_ttm REAL,
                pb REAL,
                mcap_yi REAL,
                main_net_flow REAL,
                margin_balance REAL,
                PRIMARY KEY (date, code)
            )
        """)
        conn.commit()
        return conn
    except Exception as exc:
        log.warning("fund_daily 表初始化失败: %s", exc)
        try:
            conn.close()
        except Exception:
            pass
        return None


def _identifier_to_code(identifier: str) -> str:
    return identifier.split(".")[0]


def _code_to_identifier(code: str) -> str | None:
    if not code or len(code) != 6:
        return None
    prefix = code[0]
    if prefix in ("0", "3"):
        return f"{code}.SZ"
    if prefix == "6":
        return f"{code}.SH"
    if prefix in ("4", "8"):
        return f"{code}.BJ"
    return None


def _load_from_db(
    conn: sqlite3.Connection,
    date_strs: list[str],
    all_stock_ids: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    """从 fund_daily 表加载已有数据 → {field_key: {date: {stock_id: val}}}"""
    code_set = {_identifier_to_code(s) for s in all_stock_ids}
    placeholders = ",".join("?" for _ in date_strs)
    rows = conn.execute(
        f"SELECT date, code, turnover_pct, pe_ttm, pb, mcap_yi, main_net_flow, margin_balance "
        f"FROM fund_daily WHERE date IN ({placeholders}) ORDER BY date, code",
        date_strs,
    ).fetchall()

    result: dict[str, dict[str, dict[str, float]]] = {}
    field_keys = ["turnover_pct", "pe_ttm", "pb", "mcap_yi", "main_net_flow", "margin_balance"]
    for row in rows:
        ds, code6 = row[0], row[1]
        identifier = _code_to_identifier(code6)
        if not identifier or identifier not in all_stock_ids:
            continue
        for i, fk in enumerate(field_keys):
            val = row[i + 2]
            if val is not None:
                result.setdefault(fk, {}).setdefault(ds, {})[identifier] = val

    return result


def _write_to_db(
    conn: sqlite3.Connection,
    date_str: str,
    day_data: dict[str, dict[str, float]],
):
    """写入单日数据到 fund_daily 表"""
    all_rows: list[tuple[str, str, float | None, float | None, float | None, float | None, float | None, float | None]] = []

    # code → field_values
    stock_vals: dict[str, dict[str, float | None]] = {}
    for fk, sv in day_data.items():
        for identifier, val in sv.items():
            code6 = _identifier_to_code(identifier)
            stock_vals.setdefault(code6, {})[fk] = val

    field_keys = ["turnover_pct", "pe_ttm", "pb", "mcap_yi", "main_net_flow", "margin_balance"]
    for code6, vals in stock_vals.items():
        row = [date_str, code6] + [vals.get(k) for k in field_keys]
        all_rows.append(tuple(row))

    if not all_rows:
        return

    conn.executemany(
        "INSERT OR REPLACE INTO fund_daily (date, code, turnover_pct, pe_ttm, pb, mcap_yi, main_net_flow, margin_balance) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        all_rows,
    )
    conn.commit()


def load_iwencai_panel(
    universe: str,
    period: str,
    fields: list[str] | None = None,
    stock_ids: list[str] | None = None,
    cache_dir: str | None = None,
) -> dict[str, pd.DataFrame]:
    """通过问财加载历史截面数据 panel。

    逐日遍历每个交易日，单次 API 调用获取当日截面数据。
    缓存写入 SQLite fund_daily 表 + 可选 JSON 回退。

    Parameters
    ----------
    universe: str — "all-a-share" / "csi300"
    period: str — "YYYY-MM-DD/YYYY-MM-DD"
    fields: list[str] — 问财查询字段，默认换手率/PE/PB/市值/资金流/融资余额
    stock_ids: list[str] — 限制股票列表（从已有 panel 获取）
    cache_dir: str — JSON 缓存目录（回退选项，None=不用）

    注入 panel:
        fund:turnover_pct    — 换手率
        fund:pe_ttm          — 市盈率 TTM
        fund:pb              — 市净率
        fund:mcap_yi         — 总市值(亿)
        fund:main_net_flow   — 主力资金净流入(元)
        fund:margin_balance  — 融资余额(元)
        fund:margin_change   — 融资余额日变化率（衍生）
    """
    from src.tools.alpha_bench_tool import _load_universe_panel

    # 1. 加载 OHLCV panel → 获取日期索引和股票列表
    log.info("Loading OHLCV panel: %s %s", universe, period)
    panel = _load_universe_panel(universe, period)
    if not panel:
        return {}

    close = panel.get("close")
    if close is None:
        return {}
    all_date_strs = [d.strftime("%Y-%m-%d") for d in close.index]
    all_stock_ids = list(close.columns)
    if stock_ids:
        all_stock_ids = [s for s in stock_ids if s in close.columns]

    query_fields = fields or [
        "换手率", "市盈率ttm", "市净率", "总市值",
        "主力资金净流入", "融资余额",
    ]

    field_maps = {
        "turnover_pct": ["换手率"],
        "pe_ttm": ["市盈率ttm", "滚动市盈率", "市盈率"],
        "pb": ["市净率"],
        "mcap_yi": ["总市值"],
        "main_net_flow": ["主力资金净流入", "主力资金流向", "主力资金"],
        "margin_balance": ["融资余额"],
    }

    # 2. 连接 SQLite
    db_conn = _init_fund_table()
    cache_path_obj = Path(cache_dir) if cache_dir else None
    if cache_path_obj:
        cache_path_obj.mkdir(parents=True, exist_ok=True)

    # 3. 从 DB 加载已有数据
    collected: dict[str, dict[str, dict[str, float]]] = {}
    if db_conn:
        collected = _load_from_db(db_conn, all_date_strs, all_stock_ids)
        existing_dates: set[str] = set()
        for fv in collected.values():
            existing_dates.update(fv.keys())
        log.info("  DB 已有 %d 天数据", len(existing_dates))
    else:
        existing_dates = set()

    # 4. 逐日遍历（仅缺失日期）
    n_total = len(all_date_strs)
    n_api = 0
    missing_dates = [d for d in all_date_strs if d not in existing_dates]

    for idx, date_str in enumerate(missing_dates):
        log.info("  [%d/%d] %s ...", idx + 1, len(missing_dates), date_str)
        query = f"{date_str} " + " ".join(query_fields)

        rows = None

        # JSON 缓存回退
        if cache_path_obj:
            cache_file = cache_path_obj / f"{date_str}.json"
            if cache_file.exists():
                try:
                    raw = cache_file.read_bytes()
                    rows = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    try:
                        rows = json.loads(raw.decode("gbk"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        rows = None

        if rows is None:
            n_api += 1
            rows = query_iwencai(query)
            if not rows:
                log.warning("    %s: API 返回空", date_str)
                if cache_path_obj:
                    (cache_path_obj / f"{date_str}.json").write_text(
                        json.dumps([], ensure_ascii=False), encoding="utf-8"
                    )
                continue
            if cache_path_obj:
                (cache_path_obj / f"{date_str}.json").write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            time.sleep(1.5)

        day_data = _parse_single_date_response(rows, field_maps, all_stock_ids)
        for fk, stock_vals in day_data.items():
            collected.setdefault(fk, {})[date_str] = stock_vals

        # 写入 DB
        if db_conn:
            _write_to_db(db_conn, date_str, day_data)

    if db_conn:
        db_conn.close()
    log.info("  API 调用次数: %d / 缺失 %d 天", n_api, len(missing_dates))

    # 5. 组装 panel
    n_days = len(all_date_strs)
    for field_key in ["turnover_pct", "pe_ttm", "pb", "mcap_yi", "main_net_flow", "margin_balance"]:
        field_data = collected.get(field_key, {})
        if not field_data:
            panel[f"fund:{field_key}"] = pd.DataFrame(
                index=close.index, columns=all_stock_ids, dtype=float
            )
            log.info("  fund:%s — 无数据", field_key)
            continue

        all_code_set: set[str] = set()
        for dv in field_data.values():
            all_code_set.update(dv.keys())

        wide_dict: dict[str, list[float | None]] = {
            code: [None] * n_days for code in all_code_set
        }
        date_idx_map = {d: i for i, d in enumerate(all_date_strs)}
        for ds, cv in field_data.items():
            idx = date_idx_map.get(ds)
            if idx is None:
                continue
            for code, val in cv.items():
                if code in wide_dict:
                    wide_dict[code][idx] = val

        wide = pd.DataFrame(wide_dict, index=close.index)
        wide = wide.reindex(columns=all_stock_ids)
        panel[f"fund:{field_key}"] = wide

        n_stocks = int(wide[all_stock_ids].notna().any().sum())
        log.info("  fund:%s — %d 只股票有数据", field_key, n_stocks)

    # 6. 衍生字段
    if "fund:margin_balance" in panel:
        panel["fund:margin_change"] = panel["fund:margin_balance"].pct_change(periods=1)

    log.info("问财 panel 构建完成, 共 %d 天, %d 只股票", n_days, len(all_stock_ids))
    return panel


# ═══════════════════════════════════════════════════════════════
# 下方保留旧方法作为 fallback（本地竞价 / 腾讯行情）
# ═══════════════════════════════════════════════════════════════

def load_auction_panel(universe: str, period: str, max_stocks: int | None = None, panel: dict | None = None) -> dict:
    """本地竞价数据（auction 表），见旧实现"""
    import sqlite3
    from src.tools.alpha_bench_tool import _load_universe_panel

    panel = panel if panel is not None else _load_universe_panel(universe, period)
    if not panel:
        return {}
    close = panel.get("close")
    if close is None:
        return {}
    stock_ids = list(close.columns)
    if max_stocks:
        stock_ids = stock_ids[:max_stocks]

    db_path = os.environ.get("TDX_DB_PATH", r"G:\tdx_data\tdx_daily.db")
    if not os.path.isfile(db_path):
        log.warning("DB not found: %s", db_path)
        return panel

    conn = sqlite3.connect(db_path)
    start = period.split("/")[0]
    end = period.split("/")[1]
    query = """
        SELECT date, code, auction_vol, auction_amount, auction_price
        FROM auction WHERE date >= ? AND date <= ? ORDER BY code, date
    """
    df = pd.read_sql_query(query, conn, params=(start, end))
    conn.close()
    if df.empty:
        return panel
    df["date"] = pd.to_datetime(df["date"])

    auction_vol = {}
    auction_amount = {}
    auction_price = {}
    for sid in stock_ids:
        code = _stock_code_from_identifier(sid)
        stock_df = df[df["code"] == code].sort_values("date").set_index("date")
        if stock_df.empty:
            continue
        auction_vol[sid] = stock_df["auction_vol"].astype(float)
        auction_amount[sid] = stock_df["auction_amount"].astype(float)
        auction_price[sid] = stock_df["auction_price"].astype(float)

    def _to_wide(d):
        w = pd.DataFrame(index=close.index, columns=stock_ids, dtype=float)
        for sid, s in d.items():
            common = w.index.intersection(s.index)
            w.loc[common, sid] = s.loc[common]
        return w

    panel["fund:auction_vol"] = _to_wide(auction_vol)
    panel["fund:auction_amount"] = _to_wide(auction_amount)
    panel["fund:auction_price"] = _to_wide(auction_price)
    panel["fund:auction_vol_ratio"] = (
        panel["fund:auction_vol"]
        .div(panel["fund:auction_vol"].rolling(5, min_periods=2).mean())
        .replace([np.inf, -np.inf], np.nan)
    )
    return panel


def load_concept_count_panel(universe: str, period: str, max_stocks: int | None = None, panel: dict | None = None, use_iwencai: bool = True) -> dict:
    """加载概念数量因子。

    优先用问财API（同花顺概念标签），回退到东财concept_count表。
    """
    from src.tools.alpha_bench_tool import _load_universe_panel

    panel = panel if panel is not None else _load_universe_panel(universe, period)
    if not panel:
        return {}
    close = panel.get("close")
    if close is None:
        return {}
    stock_ids = list(close.columns)

    # ── 尝试问财 ──
    if use_iwencai:
        try:
            _init_key()
            if IWENCAI_KEY:
                log.info("  Loading concept counts via 问财 ...")
                panel = _load_iwencai_concepts(panel, stock_ids, period)
                if "fund:concept_count" in panel:
                    return panel
        except Exception as e:
            log.warning("  问财concept加载失败: %s", e)

    # ── 回退东财 ──
    db_path = os.environ.get("TDX_DB_PATH", r"G:\tdx_data\tdx_daily.db")
    if not os.path.isfile(db_path):
        log.warning("DB not found: %s", db_path)
        return panel

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT code, count FROM concept_count").fetchall()
    except Exception as e:
        log.warning("concept_count table unavailable: %s", e)
        conn.close()
        return panel
    conn.close()

    code_to_count = {r[0]: r[1] for r in rows}
    wide = pd.DataFrame(index=close.index, columns=stock_ids, dtype=float)
    for sid in stock_ids:
        code = _stock_code_from_identifier(sid)
        wide[sid] = code_to_count.get(code, 0)

    panel["fund:concept_count"] = wide
    panel["fund:concept_count_log"] = np.log1p(wide)
    log.info("  fund:concept_count (东财) — %d stocks, range [%d, %d]",
             int(wide.notna().any().sum()), int(wide.min().min()), int(wide.max().max()))
    return panel


def _load_iwencai_concepts(panel: dict, stock_ids: list, period: str, min_stocks_per_concept: int = 5) -> dict:
    """Load concept counts from 问财 API, with 概念流行度过滤。

    只保留至少出现在 N 只股票中的"有效概念"，过滤极冷门概念。
    min_stocks_per_concept=5 表示只保留>=5只股票的概念。
    """
    from collections import Counter, defaultdict

    close = panel["close"]
    dates = [d.strftime("%Y-%m-%d") for d in close.index]
    period_dates = period.split("/")
    start_idx = next((i for i, d in enumerate(dates) if d >= period_dates[0]), 0)
    end_idx = next((i for i, d in enumerate(dates) if d >= period_dates[1]), len(dates))
    query_dates = dates[start_idx:end_idx]

    sample_dates = [query_dates[i] for i in range(0, len(query_dates), max(1, len(query_dates) // 10))][:10]
    if not sample_dates:
        sample_dates = query_dates[:1]

    # Step 1: Query 问财, collect (stock → list of concepts) for each sample date
    all_raw: dict[str, dict[str, list[str]]] = defaultdict(dict)  # identifier → {date → [concepts]}

    for date_str in sample_dates:
        query = f"{date_str} 所属概念"
        rows = query_iwencai(query)
        if not rows:
            log.warning("    %s: concept data empty", date_str)
            continue

        for row in rows:
            code_raw = str(row.get("股票代码", ""))
            if "." not in code_raw:
                continue
            parts = code_raw.split(".")
            identifier = f"{parts[0].strip()}.{parts[1].strip().upper()}"
            if identifier not in stock_ids:
                continue

            concept_val = row.get("所属概念")
            tags: list[str] = []
            if isinstance(concept_val, list):
                tags = concept_val
            elif isinstance(concept_val, str):
                tags = [t.strip() for t in concept_val.split(";") if t.strip()]

            all_raw[identifier][date_str] = tags

        time.sleep(1.0)

    if not all_raw:
        return panel

    # Step 2: Build global concept → stock_count from the LAST sample date (most recent)
    last_date = sample_dates[-1]
    concept_stock_counter: Counter = Counter()
    stock_concepts_last: dict[str, list[str]] = {}
    for identifier, date_data in all_raw.items():
        tags = date_data.get(last_date, [])
        stock_concepts_last[identifier] = tags
        for tag in tags:
            concept_stock_counter[tag] += 1

    # Step 3: Filter out rare concepts
    valid_concepts = {tag for tag, cnt in concept_stock_counter.items()
                      if cnt >= min_stocks_per_concept}
    log.info("  问财概念: 总数=%d, 有效(>=%d只成分股)=%d",
             len(concept_stock_counter), min_stocks_per_concept, len(valid_concepts))

    # Step 4: Count per-stock valid concept count
    n_dates = len(close.index)
    wide = pd.DataFrame(index=close.index, columns=stock_ids, dtype=float)

    for sid in stock_ids:
        tags = stock_concepts_last.get(sid, [])
        valid_count = sum(1 for t in tags if t in valid_concepts)
        wide[sid] = float(valid_count)

    panel["fund:concept_count"] = wide
    panel["fund:concept_count_log"] = np.log1p(wide)
    log.info("  fund:concept_count (问财过滤) — %d stocks, range [%d, %d], mean=%.1f",
             int(wide.notna().any().sum()), int(wide.min().min()), int(wide.max().max()),
             wide.values.mean())
    return panel


def load_margin_panel(universe: str, period: str, max_stocks: int | None = None) -> dict:
    """旧版融资融券 panel（东财 datacenter），已废弃，改用 load_iwencai_panel"""
    log.warning("load_margin_panel 已废弃，请用 load_iwencai_panel")
    return {}

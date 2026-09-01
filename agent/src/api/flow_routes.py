"""短线全流程 API（盘前→竞价→盘中→持仓→盘后）。

端点（前端经 api.tools 代理访问）：
  GET  /tools/flow/status?date=2026-08-28   全流程状态（竞价/持仓/复盘/vibe/恐惧贪婪）
  GET  /tools/flow/pre-verify?date=...     昨日 vibe 预判 vs 今日竞价实况核验
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
_PAPER_DIR = _TREE_ROOT / "paper"


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
        afgi = round(float(last.get("afgi", 50)), 1)
        state = str(last.get("afgi_state", ""))
        return {
            "date": str(last.get("date", "")),
            "afgi": afgi,
            "state": state,
            "advice": _afgi_advice(afgi),
        }
    except Exception:
        return None


def _afgi_advice(afgi: float) -> str:
    """恐惧贪婪指数 → 盘前策略建议（五档对应 AGENTS.md 分档）。"""
    if afgi < 20:
        return "极度恐惧：观察超跌反弹机会，低吸为主，轻仓试探"
    if afgi < 40:
        return "恐惧：谨慎参与，等待情绪确认信号，避免追高"
    if afgi < 60:
        return "中性：按交易计划正常参与，均衡仓位"
    if afgi < 80:
        return "贪婪：警惕高位退潮，及时止盈，控制新增仓位"
    return "极度贪婪：防退潮风险，轻仓观望，不追高"


def _file_exists_binary(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except Exception:
        return False


@router.get("/status")
def flow_status(date: str = ""):
    """全流程状态总览：竞价数据、恐惧贪婪、自选持仓与止盈止损告警、盘前/盘后产物。"""
    date_str = date or _today()
    prev = _previous_bizday(date_str)
    fear = _fear_greedy()
    holdings = _watchlist_holdings()
    return {
        "ok": True,
        "date": date_str,
        "is_today": date_str == _today(),
        "auction": _auction_info(date_str),
        "pre": {
            "fear_greedy": fear,
            "prev_bizday": prev,
            "prev_review": _file_exists_binary(_REVIEW_DIR / "ai_review" / f"{prev}_review.md"),
            "prev_vibe": _file_exists_binary(_VIBE_DIR / f"{prev}.json"),
        },
        "holdings": [holdings],
        "post": {
            "review": _file_exists_binary(_REVIEW_DIR / "ai_review" / f"{date_str}_review.md"),
            "vibe": _file_exists_binary(_VIBE_DIR / f"{date_str}.json"),
        },
    }


@router.post("/stops")
def flow_stops():
    """检查自选股持仓止盈/止损，有告警则推送企业微信。"""
    holdings = _watchlist_holdings()
    alerts = holdings["alerts"]
    _notify_watchlist_alerts(alerts)
    return {"ok": True, "alerts": alerts, "holdings": [holdings], "wecom_pushed": bool(alerts)}


@router.post("/target")
def flow_target(data: dict):
    """为自选持仓设置止盈/止损价。body: {code, price, kind('take_profit'|'stop_loss')}"""
    code = (data or {}).get("code", "").strip().lower()
    price = float((data or {}).get("price", 0) or 0)
    kind = (data or {}).get("kind", "take_profit")
    if kind not in ("take_profit", "stop_loss"):
        return {"ok": False, "error": f"kind 必须为 take_profit 或 stop_loss，收到 {kind}"}
    if not code or price <= 0:
        return {"ok": False, "error": "code 与 price(>0) 必填"}
    state = _expectation_state()
    for p in state.get("positions", []):
        if p.get("code", "").lower() == code:
            p[kind] = float(price)
            _save_expectation_state(state)
            return {"ok": True, "code": code, "price": float(price), "kind": kind}
    return {"ok": False, "error": f"自选股中未找到持仓 {code}"}


_AI_ANALYZE_SYSTEM = """你是A股短线持仓风控助手。对每只持仓股，结合现价/成本/盈亏/已有止盈止损/支撑压力，给出：
1. 持仓解读：1句话（客观、克制，不超过50字）
2. 建议止盈价：一个数字
3. 建议止损价：一个数字
4. 告警理由：若触发止损或止盈，推送用的简短理由（<30字）；未达则不写或写空串

规则：
- 止损价必须<现价，止盈价必须>现价（除非明显判断反转，仍须合理解释）
- 已有止盈/止损的持仓，尽量沿用而非推翻；只在其明显不合理时调整
- 输出严格JSON数组，不要多余文字：
[{"code":"sz000017","name":"深中华A","comment":"...","take_profit":12.5,"stop_loss":10.8,"alert_reason":""}]"""


@router.post("/analyze")
def flow_analyze(date: str = ""):
    """用 MiMo 分析当前自选持仓：解读 + 建议止盈/止损价 + 告警理由。

    body 可传 {date}；无则用今日。返回每位持仓的 LLM 结论，并缓存到
    paper/flow_holdings_ai_YYYYMMDD.json 供再次进入页面回显。
    """
    date_str = date or _today()
    logs: list[str] = []

    def _log(msg: str):
        logs.append(msg)

    holdings = _watchlist_holdings()
    positions = holdings.get("positions", [])
    if not positions:
        return {"ok": True, "positions": [], "logs": logs, "note": "无持仓可分析", "date": date_str}

    from data.tencent_quotes import add_prefix

    rows = []
    for p in positions:
        rows.append(
            " | ".join(
                [
                    f"code={p.get('code')}",
                    f"name={p.get('name')}",
                    f"cost={p.get('cost_price')}",
                    f"current={p.get('current_price')}",
                    f"take_profit={p.get('take_profit') or '-'}",
                    f"stop_loss={p.get('stop_loss') or '-'}",
                    f"support={p.get('support') or '-'}",
                    f"resistance={p.get('resistance') or '-'}",
                    f"pnl_pct={p.get('pnl_pct')}",
                ]
            )
        )

    prompt = "以下是当前自选持仓，请按规则输出建议止盈/止损价与解读：\n" + "\n".join(rows)

    try:
        from analysis.llm_analyzer import call_llm

        raw = call_llm(
            prompt,
            model="mimo-v2.5",
            system_prompt=_AI_ANALYZE_SYSTEM,
            max_tokens=4000,
            timeout=180,
            log=_log,
        )
    except Exception as e:
        return {"ok": False, "error": f"LLM 调用失败: {e}", "logs": logs}

    result = _parse_ai_analysis(raw, positions)
    result["logs"] = logs
    result["date"] = date_str
    _save_ai_analysis_cache(date_str, result)
    return result


@router.get("/analyze")
def flow_analyze_cached(date: str = ""):
    """读取某日已缓存的持仓 AI 分析（无则返回空）。"""
    date_str = date or _today()
    data = _load_ai_analysis_cache(date_str)
    if data is None:
        return {"ok": True, "positions": [], "cached": False, "date": date_str}
    data.setdefault("ok", True)
    data["cached"] = True
    data["date"] = date_str
    return data


def _ai_analysis_cache_path(date_str: str) -> Path:
    compact = date_str.replace("-", "")
    return _PAPER_DIR / f"flow_holdings_ai_{compact}.json"


def _save_ai_analysis_cache(date_str: str, result: dict):
    import json

    try:
        _PAPER_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "logs"}
        tmp = _ai_analysis_cache_path(date_str).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_ai_analysis_cache_path(date_str))
    except Exception:
        pass


def _load_ai_analysis_cache(date_str: str) -> dict | None:
    import json

    path = _ai_analysis_cache_path(date_str)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _parse_ai_analysis(raw: str, positions: list) -> dict:
    """解析 MiMo 返回的 JSON 数组，与持仓合并；解析失败时逐位降级为空。"""
    import json
    import re

    parsed = []
    try:
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end > start:
            parsed = json.loads(raw[start : end + 1])
        else:
            raise ValueError("无 JSON 数组")
        if not isinstance(parsed, list):
            raise ValueError("非数组")
    except Exception:
        parsed = []

    by_code = {}
    for item in parsed:
        if isinstance(item, dict) and item.get("code"):
            by_code[str(item["code"]).lower()] = item

    out = []
    for p in positions:
        code = str(p.get("code", "")).lower()
        ai = by_code.get(code, {})
        out.append(
            {
                "code": p.get("code"),
                "name": p.get("name"),
                "current_price": p.get("current_price"),
                "cost_price": p.get("cost_price"),
                "pnl_pct": p.get("pnl_pct"),
                "take_profit_suggestion": ai.get("take_profit"),
                "stop_loss_suggestion": ai.get("stop_loss"),
                "comment": ai.get("comment", ""),
                "alert_reason": ai.get("alert_reason", ""),
            }
        )
    return {"ok": True, "positions": out}


def _vibe_predictions(date_str: str) -> dict | None:
    """读取某日 vibe 复盘中的「明日预判」部分（focus_directions + verification_items）。

    返回 None 表示文件不存在或解析失败。
    """
    vibe_file = _VIBE_DIR / f"{date_str}.json"
    if not vibe_file.exists():
        return None
    try:
        data = json.loads(vibe_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    focus = data.get("focus") or {}
    directions = focus.get("focus_directions") or []
    verifications = focus.get("verification_items") or []
    if not directions and not verifications:
        return None
    return {
        "date": date_str,
        "emotion_phase": focus.get("emotion_phase", ""),
        "market_oneliner": focus.get("market_oneliner", ""),
        "directions": [
            {
                "direction": d.get("direction", ""),
                "logic": d.get("logic", ""),
                "risk": d.get("risk", ""),
            }
            for d in directions
        ],
        "verification_items": [
            {
                "metric": v.get("metric", ""),
                "direction": v.get("direction", ""),
                "reason": v.get("reason", ""),
            }
            for v in verifications
        ],
    }


def _auction_active_industries(date_str: str, top_n: int = 10) -> list[dict]:
    """读取当日竞价数据，按同花顺 L2 行业聚合，返回活跃行业列表。

    每条返回：{industry, stock_count, avg_chg_pct, total_amount_wan}
    按平均竞价涨幅倒序，同分按家数倒序。
    """
    from utils.config import DB_PATH

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?immutable=1", uri=True)
    except Exception:
        return []

    try:
        rows = conn.execute(
            "SELECT code, name, auction_price, prev_close, auction_amount "
            "FROM auction WHERE date=?",
            (date_str,),
        ).fetchall()
    except Exception:
        conn.close()
        return []

    if not rows:
        conn.close()
        return []

    # 裸代码 -> 带前缀代码（用于 stock_ths_industry 查询）
    def _to_prefixed(bare: str) -> str:
        if bare.startswith(("sh", "sz", "bj")):
            return bare
        if bare.startswith("6"):
            return "sh" + bare
        if bare.startswith(("0", "3")):
            return "sz" + bare
        return "bj" + bare

    prefixed = [_to_prefixed(r[0]) for r in rows]
    ind_map: dict[str, str] = {}
    try:
        placeholders = ",".join("?" * len(prefixed))
        ind_rows = conn.execute(
            f"SELECT code, industry_l2 FROM stock_ths_industry WHERE code IN ({placeholders})",
            prefixed,
        ).fetchall()
        ind_map = {r[0]: r[1] for r in ind_rows if r[1]}
    except Exception:
        pass
    conn.close()

    # 按行业聚合
    from collections import defaultdict as _dd

    ind_chgs: dict[str, list[float]] = _dd(list)
    ind_amounts: dict[str, float] = _dd(float)
    for code, name, price, prev_close, amount in rows:
        l2 = ind_map.get(_to_prefixed(code))
        if not l2:
            continue
        if prev_close and prev_close > 0 and price:
            chg = (price - prev_close) / prev_close * 100
            ind_chgs[l2].append(chg)
        if amount:
            ind_amounts[l2] += amount

    result = []
    for ind, chgs in ind_chgs.items():
        if not chgs:
            continue
        result.append({
            "industry": ind,
            "stock_count": len(chgs),
            "avg_chg_pct": round(sum(chgs) / len(chgs), 2),
            "total_amount_wan": round(ind_amounts.get(ind, 0), 0),
        })

    result.sort(key=lambda x: (-x["avg_chg_pct"], -x["stock_count"]))
    return result[:top_n]


@router.get("/pre-verify")
def flow_pre_verify(date: str = ""):
    """昨日 vibe 预判 vs 今日竞价实况核验。

    返回：
      predictions: 前一交易日的 vibe 预判（focus_directions + verification_items）
      actuals: 当日竞价活跃行业（按同花顺 L2 聚合，竞价涨幅倒序）
      prev_bizday: 前一交易日（vibe 来源日期）
    """
    date_str = date or _today()
    prev = _previous_bizday(date_str)
    return {
        "ok": True,
        "date": date_str,
        "prev_bizday": prev,
        "predictions": _vibe_predictions(prev),
        "actuals": _auction_active_industries(date_str),
    }


def register_flow_routes(app):
    """Register 短线全流程 routes on the FastAPI app."""
    app.include_router(router)


# ---------------------------------------------------------------------------
# 自选持仓（expectation_state.json 中 category=holding）止盈/止损与快照
# ---------------------------------------------------------------------------
def _expectation_state() -> dict:
    path = _PAPER_DIR / "expectation_state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"positions": []}


def _save_expectation_state(state: dict):
    path = _PAPER_DIR / "expectation_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _watchlist_holdings() -> dict:
    """自选股中的持仓股（category=holding）快照：合并实时价，计算盈亏与止盈/止损告警。"""
    from data.tencent_quotes import add_prefix, fetch_detail

    positions = [p for p in _expectation_state().get("positions", []) if p.get("category") == "holding"]
    prices = {}
    codes = [p.get("code") for p in positions if p.get("code")]
    for i in range(0, len(codes), 50):
        batch = [add_prefix(c) for c in codes[i:i + 50]]
        try:
            quotes = fetch_detail(batch)
            for full_code, q in quotes.items():
                prices[full_code] = q
        except Exception:
            continue

    holdings = []
    alerts = []
    for p in positions:
        code = p.get("code", "")
        q = prices.get(add_prefix(code)) if code else None
        current = round(float(q["price"]), 2) if q and q.get("price") else 0.0
        cost = float(p.get("cost_price") or 0)
        take_profit = float(p["take_profit"]) if p.get("take_profit") else None
        stop_loss = float(p["stop_loss"]) if p.get("stop_loss") else None
        holding = {
            "code": code,
            "name": p.get("name") or (q.get("name") if q else ""),
            "cost_price": cost,
            "current_price": current,
            "pnl_pct": round((current - cost) / cost * 100, 2) if cost and current else None,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "support": p.get("support"),
            "resistance": p.get("resistance"),
            "note": p.get("note", ""),
        }
        holdings.append(holding)
        if take_profit and current and current >= take_profit:
            alerts.append({
                "portfolio": "自选持仓",
                "code": code, "name": holding["name"],
                "reason": f"已达止盈价 {take_profit:.2f}",
                "price": current, "threshold": take_profit,
            })
        elif stop_loss and current and current <= stop_loss:
            alerts.append({
                "portfolio": "自选持仓",
                "code": code, "name": holding["name"],
                "reason": f"已破止损价 {stop_loss:.2f}",
                "price": current, "threshold": stop_loss,
            })
    return {"name": "自选持仓", "strategy": "watchlist", "positions": holdings, "alerts": alerts}


def _notify_watchlist_alerts(alerts: list):
    """有自选持仓止盈/止损告警时推送企业微信。"""
    if not alerts:
        return
    from utils.notify import send_wecom

    lines = [
        f"> **{a.get('portfolio', '自选持仓')}** 💡 {a['name']}({a['code']})\n> {a['reason']} 现价{a['price']:.2f}"
        for a in alerts
    ]
    send_wecom("自选持仓止盈/止损告警", "\n".join(lines))
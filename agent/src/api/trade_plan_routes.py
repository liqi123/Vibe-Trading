"""交易计划 API：导入 txt 交易计划 + 竞价数据到位后项目 LLM 逐条核对。

端点（前端经 api.tools 代理访问）：
  POST /tools/trade-plan/import   {date, text}     保存计划 txt（每行一条，# 开头为注释）
  GET  /tools/trade-plan/list?date=                读取计划 + 已有核对结果
  POST /tools/trade-plan/check    {date}           LLM 对照竞价数据逐条核对，落 check.json

文件落 reports/output/trade_plan/{date}/plan.txt（原始文本）与 check.json（核对结果）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import date as _date, datetime
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根
if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/trade-plan", tags=["trade-plan"])

_PLAN_ROOT = _TREE_ROOT / "reports" / "output" / "trade_plan"
_MAX_ITEMS = 100

_CHECK_SYSTEM = """你是A股短线交易计划核对员。根据“计划全文”中的阈值条件与“当日竞价数据”综合判断，禁止编造任何数字。
对每条待核对条目判断竞价阶段是否达成，输出严格 JSON 数组，无其他文字：
[{"index":0,"achieved":true,"reason":"高开2.1%达标"}]
规则：
- reason 不超过 40 字，说明关键数字依据（引用计划里的阈值或竞价数据的具体数字）
- 判断所需数据不在提供的竞价数据/计划全文里时，achieved=false，reason 以「无法判定：」开头
- index 必须与待核对条目一一对应，不得遗漏"""


def _plan_dir(date_str: str) -> Path:
    return _PLAN_ROOT / date_str


_SECTION_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]")
_NUM_RE = re.compile(r"^\d+[\.、．]\s")
_TABLE_SEP_RE = re.compile(r"^[\s\-\|:]+$")


def _parse_sections(text: str) -> list[dict]:
    """把计划按分节标题（一、二、…）切成章节。

    每节返回 {title, items, lines}：
    - items：本节内的编号条目（1. / 2、 …），作为可核对计划条目。
    - lines：本节内其它有效行（去掉表头/表格行/分隔行），作为上下文。
    表格行（含 Tab 或 |）与分隔行不作为独立条目，它们只是上下文。
    """
    sections: list[dict] = []
    title = ""
    items: list[str] = []
    lines: list[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if _SECTION_RE.match(s):
            if title or items or lines:
                sections.append({"title": title, "items": items, "lines": lines})
            title, items, lines = s, [], []
            continue
        if "|" in s or "\t" in s or _TABLE_SEP_RE.match(s):
            continue  # 表格行 → 上下文，不计为条目
        lines.append(s)
        if _NUM_RE.match(s):
            items.append(s)
    if title or items or lines:
        sections.append({"title": title, "items": items, "lines": lines})
    return sections


def _split_items(text: str) -> list[str]:
    """可核对计划条目（字符串列表）。

    - 若文档含编号条目（1. / 2、 …），只取编号行（最干净，对应“二、最终交易计划”结构）。
    - 否则回退为“每行一条”（去掉空行/# 注释/表格行/分节标题）。
    """
    sections = _parse_sections(text)
    numbered = [it for sec in sections for it in sec["items"]]
    if numbered:
        return numbered[:_MAX_ITEMS]
    flat = [ln for sec in sections for ln in sec["lines"]]
    return flat[:_MAX_ITEMS]


def _numbered_with_groups(text: str) -> tuple[list[str], list[str]]:
    """返回 (条目列表, 每条目所属分节标题)。用于前端按分节分组展示。

    无编号条目时回退为“每行一条”（分组统一为「计划」），与 _split_items 行为一致。
    """
    sections = _parse_sections(text)
    items: list[str] = []
    groups: list[str] = []
    for sec in sections:
        for it in sec["items"]:
            items.append(it)
            groups.append(sec["title"] or "计划")
    if not items:
        flat = [ln for sec in sections for ln in sec["lines"]]
        return flat[:_MAX_ITEMS], ["计划"] * len(flat[:_MAX_ITEMS])
    return items[:_MAX_ITEMS], groups[:_MAX_ITEMS]


def _validate_date(date_str: str) -> str | None:
    try:
        _date.fromisoformat(date_str)
    except ValueError:
        return f"date 须为 YYYY-MM-DD，收到 {date_str}"
    return None


def _read_plan(date_str: str) -> str | None:
    path = _plan_dir(date_str) / "plan.txt"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _read_check(date_str: str) -> dict:
    path = _plan_dir(date_str) / "check.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _merge(items: list[str], results: list[dict], groups: list[str] | None = None) -> list[dict]:
    by_idx = {int(r.get("index", -1)): r for r in results if isinstance(r.get("index"), int)}
    merged = []
    for i, text in enumerate(items):
        r = by_idx.get(i, {})
        merged.append(
            {
                "index": i,
                "text": text,
                "achieved": r.get("achieved") if r else None,
                "reason": r.get("reason", "") or "",
                "group": (groups[i] if groups and i < len(groups) else ""),
            }
        )
    return merged


def _auction_rows(date_str: str) -> list[tuple]:
    """读当日竞价数据（裸代码），返回 (code, name, auction_price, prev_close, auction_amount, vol, open_price)。"""
    from utils.config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT code, name, auction_price, prev_close, auction_amount, auction_vol, open_price "
            "FROM auction WHERE date=?",
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def _build_context(date_str: str, items: list[str]) -> dict:
    """计划相关的个股竞价明细 + 全市场竞价摘要（涨停开盘家数、高开分布、成交额前列）。"""
    joined = "\n".join(items)
    codes_in_text = set(re.findall(r"(?<!\d)(\d{6})(?!\d)", joined))
    rows = _auction_rows(date_str)
    if not rows:
        raise ValueError("该日无竞价数据")

    detail = []
    buckets = {"涨停开盘": 0, ">=5%": 0, "3~5%": 0, "0~3%": 0, "-1~0%": 0, "<-1%": 0}
    limit_open_names = []
    parsed = []
    for code, name, ap, pc, amt, vol, opx in rows:
        name = name or code
        if not pc or not ap:
            continue
        gap = (ap / pc - 1) * 100
        is_20 = code.startswith(("30", "68"))
        limit_price = round(pc * (1.2 if is_20 else 1.1), 2)
        at_limit = ap >= limit_price - 0.001
        if at_limit:
            buckets["涨停开盘"] += 1
            if len(limit_open_names) < 40:
                limit_open_names.append(f"{name}{gap:+.1f}%")
        elif gap >= 5:
            buckets[">=5%"] += 1
        elif gap >= 3:
            buckets["3~5%"] += 1
        elif gap >= 0:
            buckets["0~3%"] += 1
        elif gap >= -1:
            buckets["-1~0%"] += 1
        else:
            buckets["<-1%"] += 1
        parsed.append((code, name, gap, ap, pc, amt, vol, opx))
        if name in joined or (len(code) == 6 and code in codes_in_text):
            detail.append(
                {
                    "name": name,
                    "code": code,
                    "gap_pct": round(gap, 2),
                    "auction_price": ap,
                    "prev_close": pc,
                    "auction_amount_wan": amt,
                }
            )

    parsed.sort(key=lambda r: r[5] or 0, reverse=True)
    top_amount = [
        {"name": n, "gap_pct": round(g, 2), "auction_amount_wan": a}
        for _, n, g, _, _, a, _, _ in parsed[:20]
    ]
    big = [r for r in parsed if (r[5] or 0) >= 1000]
    big.sort(key=lambda r: r[2], reverse=True)
    top_gap = [
        {"name": n, "gap_pct": round(g, 2), "auction_amount_wan": a}
        for _, n, g, _, _, a, _, _ in big[:15]
    ]
    return {
        "date": date_str,
        "total": len(parsed),
        "collect_time": _auction_collect_time(date_str),
        "gap_buckets": buckets,
        "limit_open_top40": limit_open_names,
        "mentioned_stocks": detail[:40],
        "top_by_amount": top_amount,
        "top_gap_bigcap": top_gap,
    }


def _auction_collect_time(date_str: str) -> str | None:
    from utils.config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT MAX(collect_time) FROM auction WHERE date=?", (date_str,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _parse_check(raw: str) -> list[dict]:
    t = (raw or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    start, end = t.find("["), t.rfind("]")
    if start < 0 or end <= start:
        raise ValueError(f"LLM 返回不含 JSON 数组: {t[:120]}")
    arr = json.loads(t[start : end + 1])
    out = []
    for e in arr:
        if not isinstance(e, dict) or not isinstance(e.get("index"), int):
            continue
        out.append(
            {"index": e["index"], "achieved": bool(e.get("achieved")), "reason": str(e.get("reason") or "")[:80]}
        )
    if not out:
        raise ValueError("LLM 返回数组为空或格式不符")
    return out


def _llm_check(items: list[str], context: dict) -> list[dict]:
    from analysis.llm_analyzer import call_llm

    plan_text = "\n".join(f"[{i}] {t}" for i, t in enumerate(items))
    full = context.get("plan_full", "")
    prompt = (
        f"## 待核对计划条目（编号条目，逐条判断）\n{plan_text}\n\n"
        f"## 计划全文（含分节/锚点阈值/纪律等上下文，可参考其中的阈值条件）\n{full}\n\n"
        f"## 当日竞价数据\n{json.dumps(context, ensure_ascii=False, indent=1, default=str)}"
    )
    raw = call_llm(
        prompt,
        system_prompt=_CHECK_SYSTEM,
        max_tokens=4000,
        timeout=180,
    )
    if not raw or not str(raw).strip():
        raise ValueError("LLM 返回为空")
    if str(raw).startswith("⚠️ LLM调用失败"):
        raise ValueError(str(raw))
    return _parse_check(str(raw))


@router.post("/import")
def trade_plan_import(payload: dict | None = None, date: str = "", text: str = ""):
    """导入交易计划 txt：body {date, text}；每行一条，覆盖同日旧计划（并清除旧核对结果）。"""
    if payload:
        date = date or str(payload.get("date") or "")
        text = text or str(payload.get("text") or "")
    err = _validate_date(date)
    if err:
        return {"ok": False, "error": err}
    items = _split_items(text)
    if not items:
        return {"ok": False, "error": "计划为空：每行一条，# 开头为注释"}
    d = _plan_dir(date)
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.txt").write_text(text, encoding="utf-8")
    check = d / "check.json"
    if check.is_file():
        check.unlink()
    return {"ok": True, "date": date, "items": items, "count": len(items)}


@router.get("/list")
def trade_plan_list(date: str = ""):
    """读取某日交易计划 + 已有核对结果（未核对 achieved=null）。"""
    from data.auction_sentiment_check import get_today_str

    date_str = date or get_today_str()
    err = _validate_date(date_str)
    if err:
        return {"ok": False, "error": err}
    raw = _read_plan(date_str)
    if raw is None:
        return {"ok": True, "date": date_str, "exists": False, "items": [], "checked_at": None, "plan_full": None}
    items, groups = _numbered_with_groups(raw)
    check = _read_check(date_str)
    return {
        "ok": True,
        "date": date_str,
        "exists": True,
        "items": _merge(items, check.get("results") or [], groups),
        "checked_at": check.get("checked_at"),
        "plan_full": raw,
    }


@router.post("/check")
def trade_plan_check(payload: dict | None = None, date: str = ""):
    """竞价数据到位后逐条核对：body {date}；总是重跑 LLM 并落 check.json。"""
    if payload:
        date = date or str(payload.get("date") or "")
    from data.auction_sentiment_check import get_today_str

    date_str = date or get_today_str()
    err = _validate_date(date_str)
    if err:
        return {"ok": False, "error": err}
    raw = _read_plan(date_str)
    if raw is None:
        return {"ok": False, "error": "尚未导入交易计划"}
    items, groups = _numbered_with_groups(raw)
    try:
        context = _build_context(date_str, items)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    context["plan_full"] = raw
    try:
        results = _llm_check(items, context)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"LLM 核对失败: {exc}"}
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(
        _plan_dir(date_str) / "check.json",
        {"date": date_str, "checked_at": checked_at, "auction_collect_time": context.get("collect_time"), "results": results},
    )
    return {
        "ok": True,
        "date": date_str,
        "exists": True,
        "checked_at": checked_at,
        "items": _merge(items, results, groups),
        "plan_full": raw,
    }


def register_trade_plan_routes(app):
    """Register 交易计划 routes on the FastAPI app."""
    app.include_router(router)

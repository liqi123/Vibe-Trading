"""A 股恐惧贪婪指数（增强版 AFGI）API。

数据/计算在根项目 analysis/market_sentiment/（TDX 本地库 + 东财，免费源），
端点（前端经 api.tools 代理访问）：
  GET  /tools/sentiment/series?start=20250101&end=20260806  序列（默认近 1 年）
  POST /tools/sentiment/update                              增量更新缓存（首次约 2 分钟）
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/sentiment", tags=["sentiment"])

_COMPONENT_LABELS = [
    ("volatility_sentiment", "波动率"),
    ("volume_sentiment", "成交"),
    ("price_strength_sentiment", "股价强度"),
    ("risk_appetite_sentiment", "风险偏好"),
    ("breadth_sentiment", "市场广度"),
    ("limit_sentiment", "涨跌停"),
    ("profitability_sentiment", "赚钱效应"),
    ("sector_sentiment", "板块扩散"),
    ("style_risk_appetite", "风格"),
]


def _row_to_dict(row) -> dict:
    out = {"date": str(row.get("trade_date", ""))}
    for col, _ in _COMPONENT_LABELS:
        out[col] = round(float(row.get(col, 50.0)), 2)
    out["afgi"] = round(float(row.get("afgi", 50.0)), 2)
    out["state"] = row.get("afgi_state", "--")
    out["ma5"] = round(float(row.get("afgi_ma5", float("nan"))), 2)
    out["ma20"] = round(float(row.get("afgi_ma20", float("nan"))), 2)
    out["change"] = round(float(row.get("afgi_change", 0.0)), 2)
    for key in ("hs300", "sh", "zz1000", "cyb"):
        value = row.get(f"{key}_close", float("nan"))
        out[f"{key}_close"] = None if value is None or (isinstance(value, float) and value != value) else round(float(value), 2)
    return out


@router.get("/series")
def sentiment_series(start: str = "", end: str = ""):
    """AFGI 序列（含 9 分项），默认近 1 年。"""
    today = datetime.now().strftime("%Y%m%d")
    end = end or today
    start = start or (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    from analysis.market_sentiment.core import update_sentiment_cache

    try:
        df = update_sentiment_cache(start, end)
    except Exception as exc:  # pragma: no cover
        return {"error": f"构建失败: {exc}", "rows": []}
    if df is None or df.empty:
        return {"error": "无数据（检查数据库/网络后重试）", "rows": []}
    rows = [_row_to_dict(r) for _, r in df.iterrows()]
    latest = rows[-1]
    from analysis.market_sentiment.core import latest_indicator_table
    from analysis.market_sentiment.explanation import generate_explanation

    latest_row_data = df.iloc[-1]
    return {
        "latest": latest,
        "components": [{"key": k, "label": v} for k, v in _COMPONENT_LABELS],
        "indexes": [
            {"key": k, "label": label}
            for k, label in (("hs300", "沪深300"), ("sh", "上证综指"), ("zz1000", "中证1000"), ("cyb", "创业板指"))
        ],
        "explanation": generate_explanation(latest_row_data),
        "indicators": latest_indicator_table(latest_row_data),
        "rows": rows,
    }


@router.post("/update")
def sentiment_update():
    """增量更新缓存到最新交易日。"""
    today = datetime.now().strftime("%Y%m%d")
    from analysis.market_sentiment.core import update_sentiment_cache

    try:
        df = update_sentiment_cache("20240101", today)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "rows": 0 if df is None else len(df)}


@router.post("/ai-analysis")
def sentiment_ai_analysis(payload: dict | None = None, date: str = "", refresh: bool = False):
    """AI 深度分析：LLM 基于最新指标生成情绪解读（保留规则解读，两者并存）。

    date 可经 query (?date=20260806) 或 body ({"date": "..."}) 传入，缺省取最新交易日。
    结果按日期缓存（data/market_sentiment/ai_analysis/{date}.md），同日重复请求直接返回；
    refresh=true（query 或 body）强制重新生成并覆盖缓存。
    """
    if payload:
        date = date or payload.get("date", "")
        refresh = refresh or bool(payload.get("refresh", False))
    today = datetime.now().strftime("%Y%m%d")
    end = date or today
    start = (datetime.now() - timedelta(days=430)).strftime("%Y%m%d")
    from analysis.market_sentiment.core import update_sentiment_cache

    try:
        df = update_sentiment_cache(start, end)
        from analysis.market_sentiment.ai_analysis import generate_ai_analysis

        analysis = generate_ai_analysis(df, date or None, force=refresh)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "analysis": ""}
    return {"ok": True, "date": end, "analysis": analysis, "cached": not refresh}


def register_sentiment_routes(app):
    """Register sentiment (恐惧贪婪指数) routes on the FastAPI app."""
    app.include_router(router)

"""实时涨幅猎手 API — 筛选当前涨幅 > threshold% 的股票，标注昨日涨停。

数据/采集在根项目 data/gainers.py（腾讯实时行情 + 本地库昨日涨停判定），
端点（前端经 api.tools 代理访问）：
  GET /tools/gainers?pct=5&top=50   实时涨幅猎手
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

_TREE_ROOT = Path(__file__).resolve().parents[4]  # trading 根

if str(_TREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TREE_ROOT))

router = APIRouter(prefix="/tools/gainers", tags=["gainers"])


@router.get("")
def gainers(pct: float = 5.0, top: int = 0, sort_by: str = "chg",
            auction_min: float | None = None, max_tags: int = 5,
            tag_source: str = "industry"):
    """实时涨幅猎手：涨幅降序，昨日涨停已标注，可选按竞价涨幅筛选/排序。

    tag_source: 'industry' 同花顺二级行业（默认）| 'concept' 同花顺概念。
    """
    from data.gainers import fetch

    if tag_source not in ("industry", "concept"):
        tag_source = "industry"
    try:
        return fetch(min_pct=pct, top=top, sort_by=sort_by, auction_min=auction_min,
                     max_tags=max_tags, tag_source=tag_source)
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"扫描失败: {exc}"}


def register_gainers_routes(app):  # pragma: no cover - 注册入口
    """Register gainers (实时涨幅猎手) routes on the FastAPI app."""
    app.include_router(router)
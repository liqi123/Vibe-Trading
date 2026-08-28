"""独立网页 LLM 自动化服务（豆包 / DeepSeek / Kimi）。

与主后端（8899）解耦：Playwright 自动化偶发挂死时不再拖垮主服务。
路由与原 /tools/llm-web/* 完全一致，前端经 vite 代理（/tools/llm-web → 8902）访问。

启动：
    python llm_web_server.py          # 前台运行，端口 8902
    或 scripts/start_llm_web.bat
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI

from src.api.llm_web_routes import router

app = FastAPI(title="LLM Web Automation Service", docs_url="/llm-web-docs")
app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True, "service": "llm-web"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8902, log_level="info")

"""网页版 LLM 自动化（Playwright）：豆包 / DeepSeek / Kimi。

流程：前端点按钮 → 后端用持久化浏览器上下文打开对应网页 → 粘贴 prompt →
等待回答渲染完成 → 提取文本返回。

首次使用需先调 ``POST /tools/llm-web/login`` 打开有头浏览器手动登录，
登录态保存在 ``~/.llm-web-session/<target>/``，之后自动复用。

playwright 为可选依赖：未安装时接口返回友好错误，不影响其他功能。
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import logging
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/tools/llm-web", tags=["llm-web"])

# 异步任务状态：job_id -> {logs, done, ok, answer, detail, target}
_JOBS: dict[str, dict] = {}
_JOBS_MAX = 20  # 只保留最近 N 个任务，防内存膨胀

_SESSION_ROOT = Path.home() / ".llm-web-session"

# 集合竞价问询模板（按时间选段发送）。文件在仓库根目录，由后端读取（前端无权访问磁盘）。
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AUCTION_TEMPLATE = _REPO_ROOT / "豆包竞价问询模板.md"


def _parse_auction_stages() -> list[dict]:
    """解析豆包竞价问询模板：按 '## ' 标题切分，提取每个阶段的锚点时间与代码块内容。

    注意：代码块（``` ... ```）内部的 '## ' 行（如①内联的「## 阶段〇」）不视为阶段分隔。
    """
    if not _AUCTION_TEMPLATE.exists():
        return []
    stages: list[dict] = []
    cur: dict | None = None
    buf: list[str] = []
    in_code = False
    for line in _AUCTION_TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code and line.startswith("## "):
            if cur is not None:
                cur["prompt"] = "\n".join(buf).strip()
                if cur["prompt"]:
                    stages.append(cur)
            heading = line[3:].strip()
            m = re.search(r"(\d{1,2}):(\d{2})", heading)
            anchor = (int(m.group(1)) * 60 + int(m.group(2))) if m else None
            cur = {"heading": heading, "anchor": anchor, "prompt": ""}
            buf = []
        elif in_code and cur is not None:
            buf.append(line)
    if cur is not None:
        cur["prompt"] = "\n".join(buf).strip()
        if cur["prompt"]:
            stages.append(cur)
    return stages


def load_auction_prompt(stage_idx: int | None = None) -> tuple[str, str, int]:
    """按当前本地时间选阶段；① 内联「阶段〇 盘前准备」（直接写在模板里）。返回 (prompt, stage_label, idx)。

    stage_idx 指定时强制选该阶段（0=①~3=④），覆盖按时间自动选择；
    注：暂不使用阶段⑤（10:00 选定个股），仅取前 4 个阶段（①~④）。
    """
    stages = _parse_auction_stages()
    if not stages:
        return "", "（豆包竞价问询模板.md 缺失）", 0
    stages = stages[:4]  # 先不用阶段⑤
    if stage_idx is not None:
        stage_idx = max(0, min(int(stage_idx), len(stages) - 1))
        chosen = stages[stage_idx]
    else:
        now_min = _dt.datetime.now().hour * 60 + _dt.datetime.now().minute
        chosen = None
        for s in stages:
            if s["anchor"] is not None and s["anchor"] <= now_min:
                chosen = s
        if chosen is None:
            chosen = stages[0]
    prompt = chosen["prompt"]
    return prompt, chosen["heading"], stages.index(chosen)


# ---------------------------------------------------------------------------
# 本地实盘信号注入：调用 data/auction_sentiment_check 计算四阶段情绪，拼进 prompt，
# 让网页 LLM 基于真实本地数据做叙事综合，而非依赖其联网搜索（滞后/易编造）。
# ---------------------------------------------------------------------------
_ANALYZER = None  # 缓存已加载的分析模块


def _load_auction_analyzer():
    global _ANALYZER
    if _ANALYZER is not None:
        return _ANALYZER if _ANALYZER else None
    path = _REPO_ROOT / "data" / "auction_sentiment_check.py"
    if not path.exists():
        _ANALYZER = False
        return None
    try:
        spec = importlib.util.spec_from_file_location("auction_sentiment_check", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ANALYZER = mod
    except Exception as exc:  # noqa: BLE001
        _log.warning("加载 auction_sentiment_check 失败: %s", exc)
        _ANALYZER = False
    return _ANALYZER if _ANALYZER else None


def _format_analyzer_payload(payload: dict) -> str:
    """把 auction_sentiment_check.run() 的 payload 格式化为【详细原始数据】文本，
    不含任何结论性解读（结论由 LLM 自行给出）。仅输出 name + 原始 data + 阶段级数字/列表。"""
    if not payload:
        return ""
    lines: list[str] = []
    stages = payload.get("stages", [])

    for st in stages:
        if st.get("skip"):
            continue
        time_label = st.get("time", "")
        lines.append(f"\n### 【{time_label}】")

        # --- 各检查项原始数据（丢弃解读/信号标记，只留数值）---
        for name, data, sig, desc in st.get("signals", []):
            lines.append(f"- {name}：{data}")

        # --- 阶段级详细数据 ---
        # 阶段①：高开聚焦的全行业分布 + 代表股（让 LLM 据此判主攻方向）
        if st.get("stage") == 1:
            inds = st.get("top_industries", [])
            if inds:
                lines.append(
                    f"- 全市场高开≥3%共 {st.get('high_open', 0)} 只，"
                    f"分布于 {len(inds)} 个行业（按高开家数降序）"
                )
            for ind in inds:
                stocks_str = "、".join(
                    f"{s[1]}({s[2]:+.1f}%)" for s in ind.get("stocks", [])
                )
                lines.append(f"- 高开行业 {ind['industry']}：{ind['count']}只 -> {stocks_str}")

        # 阶段②：昨日涨停溢价细节
        if st.get("stage") == 2:
            pr = st.get("premium_ratio")
            if pr is not None:
                lines.append(f"- 昨日涨停今日溢价率：{pr:.0%}")
            avg_p = st.get("avg_now_premium")
            if avg_p is not None:
                lines.append(
                    f"- 昨日涨停当前均价涨幅：{avg_p:+.2f}%"
                    f"（{st.get('now_negative', 0)}/{st.get('total_lu', 0)} 只已翻绿）"
                )

        # 阶段③：主线板块 + 涨幅榜TOP20 + 涨跌家数
        if st.get("stage") == 3:
            ml = st.get("mainline_industry")
            if ml:
                lines.append(f"- 确认主线：{ml}")
            for item in st.get("top20", [])[:10]:
                lines.append(
                    f"  - {item['code']} {item['name']} "
                    f"{item['chg']:+.2f}% [{item.get('industry', '-')}]"
                )
            lines.append(f"- 涨停：{st.get('limit_up', 0)} | "
                         f"跌停：{st.get('limit_down', 0)} | "
                         f"上涨：{st.get('up', 0)} / 下跌：{st.get('down', 0)}")

        # 阶段④：中位数 + 指数
        if st.get("stage") == 4:
            med = st.get("median_chg")
            if med is not None:
                lines.append(f"- 全市场中位数涨幅：{med:+.2f}%")
            idx_data = st.get("indices", {})
            if idx_data:
                parts = [f"{k} {v:+.2f}%" for k, v in idx_data.items() if v is not None]
                if parts:
                    lines.append(f"- 指数：{' | '.join(parts)}")

    return "\n".join(lines)


def _inject_local_signals(prompt: str, idx: int, stage: str, date_str: str | None = None) -> str:
    """把本地实盘情绪计算结果注入 prompt。idx: 0=①盘前 1=② 2=③ 3=④ 4=⑤。

    ① 盘前：模板本就是「联网搜索完成盘前分析」，保持原样发送，不注入本地数据、不禁止联网。
    ②~④：已有本地竞价/实时信号，把「联网搜索」改写为「基于下方本地实盘数据」并注入结果。
    date_str 指定复盘日期（缺省今天实时盘），竞价/涨停等库内数据按该日期取。
    """
    if idx == 0:
        return prompt
    # 模板原本让 LLM 联网搜索；已有本地真实数据，改为基于下方数据，避免矛盾指令
    prompt = prompt.replace("联网搜索实时数据", "基于下方本地实盘数据")
    prompt = prompt.replace("联网搜索", "基于下方本地实盘数据")
    mod = _load_auction_analyzer()
    if not mod:
        return prompt
    try:
        # ②~④ 对应本地阶段 1~4；run 是累积执行（含前一阶段数据），
        # 但每个 prompt 只注入「当前阶段」的数据，不把 09:25 带进 09:35/09:45
        payload = mod.run(date_str=date_str, stage=idx, verbose=False)
        stages = [s for s in payload.get("stages", []) if not s.get("skip")]
        if stages:
            payload = {**payload, "stages": [stages[-1]]}
        text = _format_analyzer_payload(payload)
        if text:
            return (
                prompt
                + "\n\n## 本地实盘真实数据（以下为本地数据库+腾讯实时行情的真实数值，禁止编造数字）\n"
                + text
            )
    except Exception as exc:  # noqa: BLE001
        _log.warning("本地信号注入失败，回退纯模板: %s", exc)
    return prompt


def resolve_auction_prompt(stage_idx: int | None = None, use_file: bool = False, date_str: str | None = None) -> tuple[str, str, str | None]:
    """选模板阶段并注入本地实盘信号。stage_idx 指定时强制该阶段。
    date_str 指定复盘日期（缺省今天实时盘）：本地信号与该日期 xlsx 附件均按它选择。

    返回 (prompt, stage_label, file_path)：
    - 默认：注入本地信号文本，file_path=None（纯文本发送）。
    - use_file=True：跳过文本注入，改为把仓库根目录「竞价数据_YYYY-MM-DD.xlsx」
      作为附件发送；prompt 改写为「基于附件 Excel 分析」的简短指令，file_path 指向该 xlsx。
      若找不到现成文件，回退到纯文本注入（file_path=None）。
    - ① 盘前（idx=0）无竞价数据可言，始终纯文本注入，忽略 use_file。
    """
    prompt, stage, idx = load_auction_prompt(stage_idx=stage_idx)
    if not prompt:
        return prompt, stage, None
    if use_file and idx != 0:
        file_path = _resolve_auction_file(date_str)
        if not file_path:
            lg_w = _log.warning
            lg_w("未找到现成竞价文件，回退到纯文本注入")
            return _inject_local_signals(prompt, idx, stage, date_str), stage, None
        # 改写模板里的「联网搜索」指令为「基于附件 Excel」
        prompt = prompt.replace("联网搜索实时数据", "基于附件Excel数据")
        prompt = prompt.replace("联网搜索", "基于附件Excel数据")
        note = (
            "\n\n## 数据说明\n"
            "已附带 A股今日竞价全量数据文件（Excel，列：日期/代码/名称/竞价量(手)/"
            "竞价额(万元)/开盘价/昨收）。请：\n"
            "1) 计算每只涨幅 = 开盘价 / 昨收 - 1；\n"
            "2) 按行业（凭代码前缀或名称自行归类）聚合高开分布，统计各行业高开家数；\n"
            "3) 给出今日资金主攻方向判断（哪个板块竞价最强）。\n"
            "只基于附件数据，禁止编造数字。"
        )
        return prompt + note, stage, file_path
    return _inject_local_signals(prompt, idx, stage, date_str), stage, None

# 每个站点的自动化配置
_TARGETS: dict[str, dict] = {
    "doubao": {
        "url": "https://www.doubao.com/chat/",
        "input_selectors": [
            'div.tiptap.ProseMirror[contenteditable="true"]',
            '[contenteditable="true"]',
            'textarea',
        ],
        # 2026-08 豆包改版：无 data-testid；助手回答渲染在 md-box-root 容器内，
        # 用户气泡用 bg-g-send-msg-bubble-bg（不含 md-box-root），天然区分。
        "answer_selectors": [
            '[class*="md-box-root"]',
            '[class*="message-list"] [class*="container-"] > div',
        ],
        # 发送按钮：输入框有内容后，输入栏内唯一的「高亮主按钮」（bg-dbx-fill-highlight）
        # 即为发送（箭头）按钮；旧版 #flow-end-msg-send 已失效。
        # 2026-08-27 实测：当前豆包渲染为圆形箭头按钮 <button data-dbx-name="button" disabled>，
        # 且可见 textarea 是镜像（内容不进真实输入引擎 → 按钮恒 disabled）。selector 仅作
        # 兜底，真正可发送需豆包恢复可自动化（textarea 内容能被引擎识别）。
        "send_button_selectors": [
            'button[data-dbx-name="button"]:not([disabled])',
            'button.rounded-full:not([disabled])',
            'div.guidance-input-actions [class*="bg-dbx-fill-highlight"]',
            '[class*="bg-dbx-fill-highlight"]',
            "#flow-end-msg-send",
            'button[aria-label*="发送"]',
            'button[type="submit"]',
        ],
        # 豆包编辑器（TipTap/ProseMirror）同 kimi：insert_text 会把字写进 DOM 但组件
        # 内部 state 仍为空（is-editor-empty），导致发送按钮不出现；必须逐字 type。
        "prefer_key_type": True,
        # 文件上传：把现成的「竞价数据_YYYY-MM-DD.xlsx」（仓库根目录）作为附件发送。
        # 优先直接对 DOM 中的 input[type=file] 调 set_input_files；若无则点击上传按钮触发。
        "supports_file_upload": True,
        "upload_button_selectors": [
            'div.guidance-input-actions [aria-label*="附件"]',
            'div.guidance-input-actions [aria-label*="上传"]',
            'div.guidance-input-actions [aria-label*="文件"]',
            'div.guidance-input-actions [class*="icon-btn"]',
            'div.guidance-input-actions button',
            '[class*="upload"]', '[class*="attach"]', '[class*="paperclip"]',
        ],
    },
    "deepseek": {
        "url": "https://chat.deepseek.com/",
        "input_selectors": ['textarea[name="search"]', "textarea", '[contenteditable="true"]'],
        "answer_selectors": [".ds-markdown--block", ".ds-markdown"],
    },
    "kimi": {
        "url": "https://kimi.moonshot.cn/",
        "input_selectors": ['div.chat-input-editor[contenteditable="true"]', "textarea", '[contenteditable="true"]'],
        "answer_selectors": [".markdown-body", '[class*="assistant"] [class*="content"]'],
        # kimi.com 发送控件是 div.send-button-container（内含 svg，非 button 元素）
        "send_button_selectors": [
            ".send-button-container",
            '[class*="send-button"]',
        ],
        # kimi 编辑器（Vue）不认 insert_text 的整段插入——DOM 有字但组件状态仍为
        # 空（is-empty），发送按钮保持禁用；必须走逐字 type 触发完整按键事件
        "prefer_key_type": True,
    },
}

# 所有站点共享的 markdown 兜底选择器（按出现顺序取最后一个非空块）
_GENERIC_ANSWER_SEL = ".markdown-body, .ds-markdown, [class*='markdown']"


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _session_dir(target: str) -> Path:
    d = _SESSION_ROOT / target
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_first(page, selectors: list[str], timeout_ms: int = 8000):
    """依次尝试选择器，返回第一个可见的 locator；都失败返回 None。

    两阶段轮询：前 60% 时间只尝试首选选择器。页面水化期间常出现瞬态兜底
    元素（如豆包加载初期的 textarea，随后被 ProseMirror 编辑器替换），
    先给精确选择器留足挂载时间，避免拿到即将被卸载的元素。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    grace_end = time.monotonic() + timeout_ms * 0.6 / 1000
    primary, fallbacks = selectors[0], selectors[1:]
    while True:
        cands = [primary] if time.monotonic() < grace_end else [primary, *fallbacks]
        for sel in cands:
            loc = page.locator(sel).first
            try:
                if loc.is_visible():
                    return loc
            except Exception:  # noqa: BLE001 选择器失效等
                continue
        if time.monotonic() >= deadline:
            return None
        page.wait_for_timeout(400)


def _wait_answer_stable(page, baseline_len: int, timeout_s: int, job_log=None) -> bool:
    """轮询页面文本长度，连续 4 次（约 8 秒）无增长视为回答完成。"""
    def lg(msg):
        if job_log:
            job_log(msg)
    deadline = time.monotonic() + timeout_s
    stable = 0
    last_len = baseline_len
    t0 = time.monotonic()
    reported = 0
    while time.monotonic() < deadline:
        page.wait_for_timeout(2000)
        elapsed = int(time.monotonic() - t0)
        cur = len(page.inner_text("body"))
        if cur > last_len:
            if elapsed // 10 > reported:
                reported = elapsed // 10
                lg(f"回答生成中... 已等待 {elapsed}s（页面文本 {cur - baseline_len} 字符）")
            last_len = cur
            stable = 0
        else:
            stable += 1
            if stable >= 4 and last_len > baseline_len + 20:
                lg(f"回答已稳定（共 {last_len - baseline_len} 新字符，耗时 {elapsed}s）")
                return True
    return False


# 豆包 / 各站点对自动化访问的拦截页常见文案（导航成功后检测，命中即明确报错）
_BLOCK_MARKERS = [
    "安全验证", "人机验证", "验证码", "verify you are human", "verify yourself",
    "请登录后", "请先登录", "登录豆包", "登录后", "访问过于频繁", "操作过于频繁",
    "网络异常", "请稍后再试",
    "扫码登录", "微信扫码", "手机号码登录", "登录 Kimi", "获取验证码", "手机号登录",
    # Kimi 登录墙专属文案（SPA 异步弹出，初次检测常漏掉）
    "登录以同步历史", "《模型服务协议》", "已阅读同意", "微信扫码登录",
]


def _detect_block(page, job_log=None) -> str | None:
    """导航成功后检测是否被拦截（登录墙 / 人机验证 / 风控限流）。

    返回命中的拦截文案；未命中返回 None。命中说明站点在拦自动化访问，
    此时应明确报错并提示用户手动登录，而不是默默卡在导航。
    """
    def lg(msg):
        if job_log:
            job_log(msg)
    try:
        txt = (page.inner_text("body") or "")[:3000]
    except Exception:  # noqa: BLE001
        return None
    for m in _BLOCK_MARKERS:
        if m in txt:
            lg(f"⚠ 页面含拦截文案：{m}")
            return m
    try:
        u = (page.url or "").lower()
        if "login" in u or "auth" in u or "verify" in u or "captcha" in u:
            lg(f"⚠ 页面跳转到拦截地址：{page.url}")
            return "跳转到登录/验证页"
    except Exception:  # noqa: BLE001
        pass
    return None


def _maybe_new_chat(page, target: str, job_log=None) -> bool:
    """尽力开新对话，避免历史堆积 + 反复发送相同 prompt 触发风控。

    纯尽力而为。每次任务本就是全新浏览器上下文直接落在 /chat/（即新对话态），
    故仅当当前不在根 /chat/ 时才尝试快捷键 Ctrl+Shift+K（豆包侧边栏标注的热键）。
    """
    def lg(msg):
        if job_log:
            job_log(msg)
    if target != "doubao":
        return False
    path = (page.url or "").split("?")[0].rstrip("/")
    if path.endswith("doubao.com/chat"):
        return False
    try:
        page.keyboard.press("Control+Shift+K")
        page.wait_for_timeout(800)
        lg("已尝试 Ctrl+Shift+K 开新对话")
        return True
    except Exception:  # noqa: BLE001
        return False


def _debug_dump(page, target: str, tag: str, job_log=None):
    """失败时保存截图+HTML到 ~/.llm-web-session/debug/ 便于排查选择器。"""
    def lg(msg):
        _log.info("[%s] %s", target, msg)
        if job_log:
            job_log(msg)
    try:
        d = _SESSION_ROOT / "debug"
        d.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%m%d_%H%M%S")
        png = d / f"{target}_{tag}_{ts}.png"
        page.screenshot(path=str(png), full_page=True)
        html = d / f"{target}_{tag}_{ts}.html"
        html.write_text(page.content(), encoding="utf-8")
        lg(f"已保存调试文件: {png.name} / {html.name}")
    except Exception as exc:  # noqa: BLE001
        lg(f"调试文件保存失败: {exc}")


def _strip_user_prompt(text: str, prompt: str) -> str:
    """从抓取文本中剔除用户输入的 prompt 回显。

    豆包 / DeepSeek 等会把「用户发出的原文」也渲染在对话区，若不剔除，
    返回的「回复」里会混着用户自己的话，看起来就不像模型的回答了。
    """
    p = (prompt or "").strip()
    if not p:
        return text.strip()
    t = text.strip()
    if not t:
        return ""
    # 1) 整段 prompt 恰好在开头
    if t.startswith(p):
        return t[len(p):].strip()
    # 2) 较长锚点（前 120 字）在开头，容忍首尾空白/换行
    anchor = p[:120]
    if t.startswith(anchor):
        return t[len(anchor):].strip()
    # 3) 锚点出现在中段：删掉其及之前的内容（处理前面有其他回显的情况）
    idx = t.find(anchor)
    if idx > 0:
        return t[idx + len(anchor):].strip()
    return t


def _extract_answer(page, cfg: dict, baseline_text: str, prompt: str, job_log=None) -> str:
    """优先站点专属选择器取最后一块；兜底通用 markdown 类名；再兜底全文尾差。

    关键修复：豆包会把用户发出的原文也渲染在页面上，旧逻辑只掐掉 prompt 前
    80 字，导致返回内容里混着用户自己的话（「得到的哪里是豆包的回复」）。
    这里统一在返回前剔除用户 prompt 回显，并优先选择「不含用户原话」的助手
    消息块，避免把用户气泡 / 含历史的容器误当成回复。
    """
    def lg(msg):
        if job_log:
            job_log(msg)

    final_text = ""
    try:
        final_text = page.inner_text("body")
    except Exception:  # noqa: BLE001
        pass

    # 候选选择器分两档：站点专属（块本身已限定消息内容，容忍短回答）阈值 2；
    # 通用 markdown 阈值 10。均从最后一个非空块向前取（最新消息优先）。
    prompt_anchor = (prompt or "").strip()[:60]

    def _pick(sel: str, min_len: int) -> str:
        try:
            blocks = page.locator(sel)
            n = blocks.count()
            if not n:
                return ""
            lg(f"选择器 {sel} 命中 {n} 个块")
            for i in range(n - 1, -1, -1):
                txt = blocks.nth(i).inner_text().strip()
                if len(txt) < min_len:
                    continue
                if prompt_anchor and prompt_anchor in txt:
                    continue  # 含用户原话，丢弃以免回显 / 历史污染
                return txt
        except Exception:  # noqa: BLE001 选择器失效等
            pass
        return ""

    for sel in cfg["answer_selectors"]:
        txt = _pick(sel, 2)
        if txt:
            lg(f"从选择器命中块提取 {len(txt)} 字符（已规避用户 prompt 回显）")
            return txt
    txt = _pick(_GENERIC_ANSWER_SEL, 10)
    if txt:
        lg(f"从通用 markdown 块提取 {len(txt)} 字符")
        return txt

    # 兜底 A：在全文里定位「用户 prompt 回显」的最后一次出现，其后的文本即回答。
    # 豆包把用户原文渲染成气泡，回答在其后；用较长锚点（前 200 字）提高命中率。
    p = (prompt or "").strip()
    if len(p) >= 30:
        anchor = p[:200]
        idx = final_text.rfind(anchor)
        if idx > 0:
            ans = final_text[idx + len(anchor):].strip()
            if len(ans) >= 10:
                lg(f"按 prompt 回显位置提取回答 {len(ans)} 字符")
                return ans
        # 锚点可能因换行/格式略有差异，退而求其次：取前 60 字做签名
        sig = p[:60]
        idx2 = final_text.rfind(sig)
        if idx2 > 0:
            # 从签名后往前找空白/换行，尽量避免截断半句
            rest = final_text[idx2 + len(sig):]
            ans = rest.strip()
            if len(ans) >= 10:
                lg(f"按 prompt 签名提取回答 {len(ans)} 字符")
                return ans

    # 兜底 B：整页文本尾部差值（去掉回显的 prompt）
    lg("选择器未命中合适块，改用全文尾差兜底提取")
    diff_len = max(0, len(final_text) - len(baseline_text))
    if diff_len < 30:
        return ""
    tail = final_text[-diff_len:]
    return _strip_user_prompt(tail, prompt)


def _dismiss_modal(page, job_log=None):
    """关闭站点弹出的遮罩对话框（如下载 App 推广），避免其拦截编辑器点击导致写入失败。

    豆包进入会话时常弹出「下载电脑版」模态（role=dialog 覆盖全屏），若不打掉，
    后续 box.click() 会被对话框拦截 -> 编辑器收不到焦点 -> 文字写不进 -> 发送按钮永不出现。
    """
    def lg(msg):
        if job_log:
            job_log(msg)

    try:
        dlg = page.locator('[role="dialog"][data-state="open"]').first
        if not dlg.is_visible():
            return
        lg("检测到遮罩对话框，尝试关闭...")
        try:
            close_btn = dlg.locator('button[aria-label="关闭"]').first
            if close_btn.is_visible():
                close_btn.click()
            else:
                page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        if page.locator('[role="dialog"][data-state="open"]').first.is_visible():
            lg("⚠ 对话框仍未关闭，发送可能受影响")
        else:
            lg("✓ 已关闭遮罩对话框")
    except Exception:  # noqa: BLE001
        pass


def _resolve_auction_file(date_str: str | None = None) -> str | None:
    """返回仓库根目录现成的「竞价数据_YYYY-MM-DD.xlsx」路径（采集后自动导出）。

    优先匹配指定日期；缺省用今天；都不存在则回退到最新一个。找不到返回 None。
    """
    from datetime import date as _dt

    d = date_str or _dt.today().isoformat()
    p = _REPO_ROOT / f"竞价数据_{d}.xlsx"
    if p.exists():
        return str(p)
    cands = sorted(_REPO_ROOT.glob("竞价数据_*.xlsx"), reverse=True)
    return str(cands[0]) if cands else None


def _xlsx_to_csv(xlsx_path: str) -> str | None:
    """xlsx 不被接受时转 csv 兜底（临时目录，不污染仓库）。失败返回 None。"""
    try:
        import pandas as pd
        import tempfile
        from pathlib import Path as _P

        df = pd.read_excel(xlsx_path)
        out = _P(tempfile.gettempdir()) / (_P(xlsx_path).stem + ".csv")
        df.to_csv(str(out), index=False, encoding="utf-8-sig")
        return str(out)
    except Exception as exc:  # noqa: BLE001
        _log.warning("xlsx->csv 失败: %s", exc)
        return None


def _set_input_files(fi, path: str, lg) -> bool:
    """对 file input 设文件；xlsx 类型被拒时自动转 csv 重试。"""
    try:
        fi.set_input_files(path)
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "type" in msg or "allow" in msg:
            csvp = _xlsx_to_csv(path)
            if csvp:
                try:
                    fi.set_input_files(csvp)
                    lg("xlsx 类型不被接受，已转 csv 重试")
                    return True
                except Exception:  # noqa: BLE001
                    pass
        lg(f"✗ set_input_files 失败: {str(exc)[:100]}")
        return False


def _wait_file_attached(page, lg, timeout_ms: int = 8000) -> bool:
    """乐观等待附件确认标记；即便没检测到文本也返回 True（让发送继续）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            body = page.inner_text("body") or ""
        except Exception:  # noqa: BLE001
            body = ""
        if "竞价数据" in body or ".xlsx" in body or ".csv" in body or "附件" in body or "个文件" in body:
            lg("✓ 附件已出现在对话区")
            return True
        page.wait_for_timeout(500)
    lg("⚠ 未检测到附件确认文本（可能已上传但无提示），继续发送")
    return True


def _upload_file(page, cfg: dict, file_path: str, job_log=None) -> bool:
    """把本地文件作为附件上传到当前对话。成功返回 True（即便乐观等待未确认）。

    策略：先试 DOM 中已存在的 input[type=file]（最稳）；否则点击上传按钮触发。
    """
    def lg(msg):
        if job_log:
            job_log(msg)

    import os

    if not os.path.exists(file_path):
        lg(f"✗ 上传文件不存在: {file_path}")
        return False

    # 1) DOM 中已有 input[type=file]：直接注入（无需点击，最稳）
    try:
        fi = page.locator('input[type="file"]').first
        if fi.count() > 0:
            if _set_input_files(fi, file_path, lg):
                return _wait_file_attached(page, lg)
    except Exception as exc:  # noqa: BLE001
        lg(f"直接 set_input_files 失败，尝试点击上传按钮: {str(exc)[:80]}")

    # 2) 点击上传按钮 → 等待 input[type=file] 出现 → 注入
    for sel in cfg.get("upload_button_selectors", []):
        try:
            btn = page.locator(sel).first
            if not btn.is_visible(timeout=2000):
                continue
            btn.click()
            page.wait_for_timeout(800)
            fi = page.locator('input[type="file"]').first
            if fi.count() > 0 and _set_input_files(fi, file_path, lg):
                return _wait_file_attached(page, lg)
        except Exception:  # noqa: BLE001 选择器失效等
            continue

    lg("✗ 未找到上传入口（按钮/文件框均不可见），回退纯文本发送")
    return False


def _try_send(page, cfg: dict, prompt: str, job_log=None) -> bool:
    """发送消息并验证：重新定位输入框 → 写入 → 校验 → Enter/按钮发送。

    豆包等站点用 ProseMirror/TipTap 富文本编辑器（contenteditable div，
    非 textarea）。这类编辑器对 ``fill()`` 无效，且 ``click()+insert_text``
    偶尔因焦点未到位而写入 0 字符。这里统一：聚焦→清空→键盘输入→校验。
    """
    def lg(msg):
        if job_log:
            job_log(msg)

    # 先关掉可能遮挡编辑器的弹窗（豆包会弹「下载电脑版」推广等）
    _dismiss_modal(page, job_log=job_log)

    # 页面可能已重渲染，重新定位输入框
    box = _find_first(page, cfg["input_selectors"], timeout_ms=6000)
    if box is None:
        lg("✗ 发送时输入框已消失（页面跳转或改版）")
        return False

    def _read_back() -> str:
        try:
            editable = box.evaluate("el => el.isContentEditable === true")
            if editable:
                return box.inner_text() or ""
            return box.input_value() or ""
        except Exception:  # noqa: BLE001 元素失效
            return ""

    def _write_into_editable() -> bool:
        """针对 contenteditable / ProseMirror 的稳健写入。返回是否成功。"""
        try:
            box.click()  # 聚焦编辑器
            page.wait_for_timeout(300)
            # 清空可能存在的旧内容（Ctrl+A + Delete）
            page.keyboard.press("Control+A")
            page.wait_for_timeout(80)
            page.keyboard.press("Delete")
            page.wait_for_timeout(120)
            # 先试 insert_text（快）；若校验失败再退回逐字 type（慢但稳）。
            # prefer_key_type 的站点（kimi）跳过 insert_text，直接逐字输入。
            if not cfg.get("prefer_key_type"):
                page.keyboard.insert_text(prompt)
                page.wait_for_timeout(300)
                got = _read_back()
                if got.strip():
                    return True
                lg("insert_text 未生效，改逐字 type...")
            box.click()
            page.wait_for_timeout(200)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(100)
            page.keyboard.type(prompt, delay=8)
            page.wait_for_timeout(300)
            return bool(_read_back().strip())
        except Exception as exc:  # noqa: BLE001
            lg(f"✗ 编辑器写入异常: {str(exc)[:120]}")
            return False

    ok = False
    try:
        editable = box.evaluate("el => el.isContentEditable === true")
        if editable:
            ok = _write_into_editable()
        else:
            try:
                box.fill(prompt, timeout=4000)
                ok = bool(_read_back().strip())
            except Exception:
                # 瞬态 textarea（水化前）可能已被替换成编辑器，重新定位再写
                lg("写入目标疑似瞬态元素，重新定位输入框...")
                relocated = _find_first(page, cfg["input_selectors"], timeout_ms=8000)
                if relocated is not None:
                    box = relocated
                if box.evaluate("el => el.isContentEditable === true"):
                    ok = _write_into_editable()
                else:
                    box.fill(prompt, timeout=4000)
                    ok = bool(_read_back().strip())
    except Exception as exc:  # noqa: BLE001
        lg(f"✗ 写入 prompt 失败: {str(exc)[:120]}")
        return False

    got = _read_back()
    lg(f"写入校验：输入框当前 {len(got)} 字符（预期 {len(prompt)}）")
    if not ok or got.strip() == "":
        lg("✗ 写入未生效")
        return False

    def _fresh_read() -> str | None:
        """重新定位输入框再读内容。返回 None 表示元素已卸载（会话可能已切换）。"""
        fresh = _find_first(page, cfg["input_selectors"], timeout_ms=2000)
        if fresh is None:
            return None
        try:
            editable = fresh.evaluate("el => el.isContentEditable === true")
            txt = (fresh.inner_text() or "") if editable else (fresh.input_value() or "")
            return txt.strip()
        except Exception:  # noqa: BLE001 元素失联
            return ""

    def _confirm_sent(via: str) -> bool:
        """发送确认：轮询输入框被清空（旧 locator 失联导致的假空串不再误判）。"""
        want = len(got.strip())
        for _ in range(6):
            val = _fresh_read()
            if val is None or len(val) < max(0, want - 2):
                lg(f"✓ 发送成功（{via}）")
                return True
            page.wait_for_timeout(500)
        return False

    page.wait_for_timeout(800)
    # 优先点击发送按钮（豆包 2026-08 改版后 Enter 不再可靠提交）
    for sel in cfg.get("send_button_selectors", []):
        try:
            btn = page.locator(sel).first
            if not btn.is_visible():
                continue
            if (btn.get_attribute("aria-disabled") or "").strip().lower() == "true":
                lg(f"发送按钮不可用（{sel} aria-disabled），跳过")
                continue
            if btn.is_disabled():
                lg(f"发送按钮 disabled（{sel}），跳过")
                continue
            btn.click()
            page.wait_for_timeout(1000)
            if _confirm_sent(f"按钮 {sel}"):
                return True
        except Exception:  # noqa: BLE001 选择器失效等
            continue

    # 回退：Enter 键提交
    lg("按钮未生效，回退 Enter 发送...")
    try:
        box.click()
    except Exception:  # noqa: BLE001
        pass
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    if _confirm_sent("Enter"):
        return True

    lg("✗ 所有发送方式均失败")
    return False


def _run_ask(target: str, prompt: str, timeout_s: int, job_log=None, file_path: str | None = None) -> tuple[str, str]:
    """执行一次问答。返回 (answer, error)；成功时 error 为空。

    file_path 非空时，发送文本前先将其作为附件上传（若目标支持文件上传）。
    """
    def lg(msg):
        _log.info("[%s] %s", target, msg)
        if job_log:
            job_log(msg)

    sync_pw = _import_playwright()
    if sync_pw is None:
        return "", "未安装 playwright：pip install playwright && playwright install chromium"
    cfg = _TARGETS[target]
    lg(f"启动浏览器（headless）→ {cfg['url']}")
    pw = sync_pw().start()
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(_session_dir(target)),
            headless=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            # 反检测：尽量降低无头浏览器被站点识别为自动化的概率
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
        )
        try:  # 注入脚本覆盖 navigator.webdriver 标记
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(10_000)

            # ---- 导航：3 次重试，超时递增（30→45→60s）----
            nav_ok = False
            for attempt, goto_tmo in enumerate([30_000, 45_000, 60_000]):
                try:
                    lg(f"正在打开页面（第{attempt+1}次，超时{goto_tmo//1000}s）...")
                    page.goto(cfg["url"], timeout=goto_tmo, wait_until="domcontentloaded")
                    nav_ok = True
                    lg(f"页面已加载: {page.url}")
                    break
                except Exception as exc:
                    lg(f"⚠ 第{attempt+1}次导航失败: {str(exc)[:100]}")
                    if attempt < 2:
                        time.sleep(3)
                        try:
                            page = ctx.pages[0] if ctx.pages else ctx.new_page()
                        except Exception:
                            pass
                    else:
                        lg("✗ 导航全部失败")
                        _debug_dump(page, target, "nav_fail", job_log=lg)
                        return "", f"无法打开 {cfg['url']}：网络超时或站点拦截（已保存调试截图 ~/.llm-web-session/debug/）"

            if not nav_ok:
                return "", "导航失败"

            # Kimi 等 SPA 在导航后异步校验登录态，登录墙常延迟 1~3s 才弹出；
            # 先等 SPA 水化 + 鉴权结果落定，再做拦截判定，避免漏检。
            page.wait_for_timeout(3500)

            # 导航成功 → 先判断是否被站点拦截（登录墙/人机验证/风控）
            block = _detect_block(page, job_log=lg)
            if block:
                lg(f"✗ 检测到拦截页：{block}")
                _debug_dump(page, target, "blocked", job_log=lg)
                return "", (
                    f"{target} 拦截了自动化访问（{block}），登录态可能已失效。"
                    f"请手动打开有头浏览器登录/通过验证后重试：POST /tools/llm-web/login"
                )

            # 尽量开新对话，避免历史堆积 + 重复 prompt 触发风控
            _maybe_new_chat(page, target, job_log=lg)

            lg("定位输入框...")
            box = _find_first(page, cfg["input_selectors"], timeout_ms=15_000)
            if box is None:
                lg("✗ 15秒内未找到输入框")
                _debug_dump(page, target, "no_input", job_log=lg)
                return "", "找不到输入框：可能未登录或页面改版（已保存调试截图到 ~/.llm-web-session/debug/）"
            lg(f"找到输入框（{box.evaluate('el => el.tagName.toLowerCase()')}）")

            # 文件上传（在写文本+发送之前）：把现成竞价 xlsx 作为附件发给目标
            if file_path and cfg.get("supports_file_upload"):
                lg(f"尝试上传附件: {file_path}")
                uploaded = _upload_file(page, cfg, file_path, job_log=lg)
                lg("✓ 附件已上传" if uploaded else "⚠ 附件上传失败，将仅发文本")

            # 二次拦截检查：Kimi 登录墙常在导航后异步弹出，初次检查时尚未渲染，
            # 此时输入框（被遮罩挡住的编辑器）已被 Playwright 判定为「可见」，
            # 若直接发送会把文字打进被遮罩拦截的框里静默失败。
            block = _detect_block(page, job_log=lg)
            if block:
                lg(f"✗ 发送前检测到拦截页：{block}")
                _debug_dump(page, target, "blocked", job_log=lg)
                return "", (
                    f"{target} 拦截了自动化访问（{block}），登录态可能已失效。"
                    f"请手动登录后重试：POST /tools/llm-web/login"
                )

            baseline_len = len(page.inner_text("body"))
            baseline_text = ""
            try:
                baseline_text = page.inner_text("body")
            except Exception:  # noqa: BLE001
                pass

            if not _try_send(page, cfg, prompt, job_log=lg):
                _debug_dump(page, target, "send_fail", job_log=lg)
                return "", "消息发送失败：写入/Enter/发送按钮均未生效（详见调试截图 ~/.llm-web-session/debug/）"

            lg("已发送，等待回答开始生成...")

            ok = _wait_answer_stable(page, baseline_len, timeout_s=max(60, timeout_s), job_log=lg)
            cur_len = len(page.inner_text("body"))
            if cur_len <= baseline_len + 20:
                # 文本增长很少：可能是极短回答（如「收到」）或尚未开始生成。
                # 不再据此直接判失败，继续尝试提取——能取到回答即视为成功。
                lg(f"⚠ 页面文本增长较少（{baseline_len} → {cur_len}），疑似短回答或尚未生成，继续提取")

            lg("提取回答文本...")
            answer = _extract_answer(page, cfg, baseline_text, prompt, job_log=lg)
            if not answer:
                lg("✗ 所有选择器均未提取到回答")
                _debug_dump(page, target, "extract_fail", job_log=lg)
                return "", "未能提取到回答：页面可能改版（已保存调试截图到 ~/.llm-web-session/debug/）"
            lg(f"✓ 提取成功：{len(answer)} 字符")
            if not ok:
                lg(f"⚠ 回答超 {timeout_s}s 仍在变化，返回当前已生成部分")
            return answer, ""
        finally:
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass
    finally:
        pw.stop()


@router.post("/login")
def llm_web_login(data: dict):
    """打开有头浏览器让用户手动登录指定站点，浏览器关闭后保存会话。"""
    target = (data or {}).get("target", "")
    if target not in _TARGETS:
        return {"ok": False, "detail": f"未知目标: {target}，可选 {list(_TARGETS)}"}
    sync_pw = _import_playwright()
    if sync_pw is None:
        return {"ok": False, "detail": "未安装 playwright"}
    pw = sync_pw().start()
    try:
        ctx = pw.chromium.launch_persistent_context(str(_session_dir(target)), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(_TARGETS[target]["url"])
        _log.info("%s 登录窗口已打开，等待用户完成登录并关闭浏览器...", target)
        try:
            while True:
                if not ctx.browser or not ctx.pages:
                    break
                # 用户关闭最后一个标签页即退出
                alive = [p for p in ctx.pages if not p.is_closed()]
                if not alive:
                    break
                time.sleep(2)
        except Exception:  # noqa: BLE001 浏览器被用户直接杀掉
            pass
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        pw.stop()
    return {"ok": True, "detail": f"{target} 登录态已保存到 {_session_dir(target)}"}


@router.post("/ask")
def llm_web_ask(data: dict):
    """向网页版 LLM 提问（异步）。Body: {target, prompt?, timeout_s?, use_template?}

    - 传 prompt：使用给定文本。
    - 传 use_template=true：改用根目录「豆包竞价问询模板.md」，按当前时间选阶段发送。
      可选 stage（0~3）强制指定阶段（①~④），覆盖按时间自动选择。
      立即返回 {job_id}，进度用 GET /tools/llm-web/progress/{job_id} 轮询。
    """
    data = data or {}
    target = data.get("target", "")
    prompt = (data.get("prompt") or "").strip()
    timeout_s = int(data.get("timeout_s") or 120)

    if target not in _TARGETS:
        return {"ok": False, "detail": f"未知目标: {target}"}

    if data.get("use_template"):
        stage_arg = data.get("stage")
        if stage_arg is not None and str(stage_arg).isdigit():
            stage_arg = int(stage_arg)
        else:
            stage_arg = None
        use_file = bool(data.get("use_file"))
        date_str = (data.get("date") or "").strip() or None
        prompt, stage, file_path = resolve_auction_prompt(
            stage_idx=stage_arg, use_file=use_file, date_str=date_str
        )
        if not prompt:
            return {"ok": False, "detail": "竞价问询模板读取失败（豆包竞价问询模板.md 缺失）"}
        # 把所选阶段记进 job，便于前端展示
        data["_stage"] = stage
        data["_file_path"] = file_path

    if not prompt:
        return {"ok": False, "detail": "prompt 不能为空"}

    # 清理旧任务
    if len(_JOBS) >= _JOBS_MAX:
        for k in sorted(_JOBS, key=lambda k: _JOBS[k].get("created", 0))[: len(_JOBS) - _JOBS_MAX + 1]:
            _JOBS.pop(k, None)

    job_id = uuid.uuid4().hex[:12]
    job: dict = {
        "job_id": job_id,
        "target": target,
        "logs": [],
        "done": False,
        "ok": None,
        "answer": "",
        "detail": "",
        "elapsed_s": None,
        "created": time.time(),
    }

    def job_log(msg: str):
        ts = time.strftime("%H:%M:%S")
        job["logs"].append(f"[{ts}] {msg}")

    def worker():
        t0 = time.monotonic()
        try:
            answer, err = _run_ask(
                target, prompt, timeout_s, job_log=job_log,
                file_path=data.get("_file_path"),
            )
            elapsed = round(time.monotonic() - t0, 1)
            job["elapsed_s"] = elapsed
            if err:
                job["ok"] = False
                job["detail"] = err
                job_log(f"✗ 失败（{elapsed}s）: {err}")
            else:
                job["ok"] = True
                job["answer"] = answer
                job_log(f"✓ 完成（{elapsed}s），回答 {len(answer)} 字符")
        except Exception as exc:  # noqa: BLE001
            job["ok"] = False
            job["detail"] = f"自动化异常: {exc}"
            job_log(f"✗ 异常: {exc}")
            _log.warning("llm_web_ask(%s) failed", target, exc_info=True)
        finally:
            job["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    _JOBS[job_id] = job
    return {"ok": True, "job_id": job_id}


@router.get("/progress/{job_id}")
def llm_web_progress(job_id: str):
    """轮询任务进度：{done, ok, answer, detail, logs[]}"""
    job = _JOBS.get(job_id)
    if not job:
        return {"ok": False, "detail": f"任务不存在或已过期: {job_id}"}
    return {
        "ok": True,
        "done": job["done"],
        "success": job["ok"],
        "answer": job["answer"],
        "detail": job["detail"],
        "logs": list(job["logs"]),
        "elapsed_s": job["elapsed_s"],
        "target": job["target"],
    }


@router.get("/status")
def llm_web_status():
    """检查 playwright 是否可用、各站点是否有已保存的登录态目录。"""
    installed = _import_playwright() is not None
    chromium_ok = False
    if installed:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                chromium_ok = pw.chromium.executable_path and Path(pw.chromium.executable_path).exists()
        except Exception:  # noqa: BLE001
            chromium_ok = False
    sessions = {t: (_SESSION_ROOT / t).exists() for t in _TARGETS}
    return {"ok": True, "playwright_installed": installed, "chromium_ready": bool(chromium_ok), "sessions": sessions}


@router.get("/auction-prompt")
def llm_web_auction_prompt(stage: int | None = None, use_file: bool = False, date: str = "") -> dict:
    """返回应发的竞价问询 prompt（含本地信号注入），供前端预览。stage 指定时强制该阶段。
    date 指定复盘日期（缺省今天实时盘），本地信号按该日期取。

    use_file=true 时返回带附件说明的 prompt，并在 file_path 字段给出现成 xlsx 路径。
    """
    date_str = date.strip() or None
    prompt, stage_label, file_path = resolve_auction_prompt(
        stage_idx=stage, use_file=bool(use_file), date_str=date_str
    )
    return {"ok": True, "stage": stage_label, "prompt": prompt, "file_path": file_path}


def register_llm_web_routes(app, require_auth=None):
    dependencies = []
    if require_auth is not None:
        dependencies = [require_auth]
    app.include_router(router, dependencies=dependencies)

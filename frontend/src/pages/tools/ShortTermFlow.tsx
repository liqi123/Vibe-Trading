import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  AlarmClock,
  BarChart3,
  Bell,
  Brain,
  CalendarClock,
  CheckCircle2,
  ChevronUp,
  Clipboard,
  Crosshair,
  FileText,
  Loader2,
  Maximize2,
  Play,
  RefreshCw,
  Sun,
  Target,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useLLMWebAsk } from "@/hooks/useLLMWebAsk";
import { LLMManualPaste, type ManualAnswer } from "@/components/llm/LLMManualPaste";
import { AuctionSentiment } from "./AuctionSentiment";

interface Position {
  code: string;
  name: string;
  cost_price: number;
  current_price: number;
  pnl_pct: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  support?: number | null;
  resistance?: number | null;
  note?: string;
}
interface Alert {
  portfolio?: string;
  code: string;
  name: string;
  reason: string;
  price: number;
  threshold?: number;
}
interface Portfolio {
  name: string;
  strategy: string;
  return_pct: number;
  total: number;
  cash: number;
  positions: Position[];
  alerts: Alert[];
}
interface AiPosition {
  code: string;
  name: string;
  current_price: number | null;
  cost_price: number | null;
  pnl_pct: number | null;
  take_profit_suggestion: number | null;
  stop_loss_suggestion: number | null;
  comment: string;
  alert_reason: string;
}
interface FlowStatus {
  ok: boolean;
  date: string;
  is_today: boolean;
  auction: { exists: boolean; count: number; collect_time?: string | null };
  pre: {
    fear_greedy?: { date: string; afgi: number; state: string; advice?: string } | null;
    prev_bizday: string;
    prev_review: boolean;
    prev_vibe: boolean;
  };
  holdings: Portfolio[];
  post: { review: boolean; vibe: boolean };
}
interface VibeDirection {
  direction: string;
  logic: string;
  risk: string;
}
interface VibeVerificationItem {
  metric: string;
  direction: string;
  reason: string;
}
interface VibePredictions {
  date: string;
  emotion_phase: string;
  market_oneliner: string;
  directions: VibeDirection[];
  verification_items: VibeVerificationItem[];
}
interface AuctionIndustry {
  industry: string;
  stock_count: number;
  avg_chg_pct: number;
  total_amount_wan: number;
}
interface PreVerify {
  ok: boolean;
  date: string;
  prev_bizday: string;
  predictions: VibePredictions | null;
  actuals: AuctionIndustry[];
}

const chip = (ok: boolean) =>
  ok
    ? "px-2 py-0.5 text-xs rounded-full bg-green-500/15 text-green-600 border border-green-500/30"
    : "px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground border";

function SectionHeader({ icon: Icon, title, time, color, right }: { icon: any; title: string; time: string; color: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Icon className={`h-5 w-5 ${color}`} />
      <h2 className="font-semibold text-base">{title}</h2>
      <span className="text-xs text-muted-foreground">{time}</span>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

// 复盘多源分析：豆包 + DeepSeek（与竞价看板一致，走网页 LLM）
const REVIEW_LLM = [
  { key: "doubao", label: "豆包" },
  { key: "deepseek", label: "DeepSeek" },
];

// 盘前预演多源分析：豆包 + DeepSeek + Kimi（多加一路做交叉验证）
const PREVIEW_LLM = [
  { key: "doubao", label: "豆包" },
  { key: "deepseek", label: "DeepSeek" },
  { key: "kimi", label: "Kimi" },
];

/** 从 MiMo 综合结果中提取「【最终结论】」浓缩段；未命中返回空串（前端回退显示全文）。 */
function extractConclusion(report: string): string {
  const marker = "【最终结论】";
  const idx = report.lastIndexOf(marker);
  if (idx < 0) return "";
  return report.slice(idx + marker.length).replace(/^[：:。\s]+/, "").trim();
}

// 结论在弹窗内默认只展示前 200 字，超出则给出「查看完整结论」按钮，点击弹窗展示全文
const CONCLUSION_PREVIEW_LEN = 200;

/** 盘前「昨日复盘」卡的只读结果展示：回显 localStorage 缓存的 AI 综合结论（不再从盘前触发询问）。 */
function ReviewAIResultPreview({
  date,
  kind = "review",
  emptyText = "结果未生成：盘后「AI 复盘」运行后，此处展示综合结论",
}: {
  date: string;
  kind?: "review" | "preview";
  emptyText?: string;
}) {
  const [state, setState] = useState<null | { content: string; mtime?: string }>(null);
  const [loading, setLoading] = useState(true);
  const [fullOpen, setFullOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.tools
      .get<{ exists: boolean; content?: string; mtime?: string }>(`/review/report?date=${date}&kind=${kind}`)
      .then((r) => {
        if (!alive) return;
        setState(r?.exists && r.content ? { content: r.content, mtime: r.mtime } : null);
        setLoading(false);
      })
      .catch(() => {
        if (alive) {
          setState(null);
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [date, kind]);
  if (loading) return <p className="mt-1 text-xs text-muted-foreground">读取本地结果…</p>;
  if (!state) return <p className="mt-1 text-xs text-muted-foreground">{emptyText}</p>;
  const plain = state.content
    .replace(/[#>*`~|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  // 优先提取「【最终结论】」浓缩段；无标记时退回全文（去除 markdown 符号的纯文本）
  const conclusion = extractConclusion(state.content) || plain;
  const long = conclusion.length > 110;
  return (
    <>
      <div className="mt-1 text-xs leading-relaxed">
        <p className="text-foreground/80">
          {conclusion.slice(0, 110)}
          {long ? "…" : ""}
        </p>
        <p className="mt-1 text-muted-foreground">综合结论 {conclusion.length} 字 · 生成于 {state.mtime ?? "—"}</p>
        <button
          onClick={() => setFullOpen(true)}
          className="mt-1.5 flex items-center gap-1.5 px-3 py-1.5 text-xs border rounded-md hover:bg-muted transition-colors"
        >
          <Maximize2 className="h-3.5 w-3.5" /> 查看完整复盘
        </button>
      </div>

      {/* 完整复盘弹窗：展示整篇 md（含各来源原始回答 + 项目 LLM 综合结论） */}
      {fullOpen && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-[60] p-4"
          onClick={() => setFullOpen(false)}
        >
          <div
            className="bg-card border rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-semibold">{kind === "preview" ? "AI 今日预演" : "AI 复盘"} · 完整复盘</h3>
              <button
                onClick={() => setFullOpen(false)}
                className="text-muted-foreground hover:text-foreground text-xl leading-none"
              >
                ×
              </button>
            </div>
            <div className="p-4 overflow-y-auto">
              <div className="prose prose-sm prose-invert max-w-none text-foreground">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.content}</ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ReviewAIModal({
  date,
  open,
  onClose,
  mode = "review",
}: {
  date: string;
  open: boolean;
  onClose: () => void;
  /** review=复盘（合集六+七，分析当天）；preview=今日预演（合集二+七，盘前研判当日）；verify=盘后验证（早晨预演 vs 收盘） */
  mode?: "review" | "preview" | "verify";
}) {
  const isPreview = mode === "preview";
  const isVerify = mode === "verify";
  /** 预演走三路（含 Kimi）做交叉验证，复盘仍为豆包 + DeepSeek。 */
  const TARGETS = isPreview ? PREVIEW_LLM : REVIEW_LLM;
  const TARGET_LABELS = TARGETS.map((t) => t.label).join(" + ");
  const { askOne } = useLLMWebAsk();
  const [stage, setStage] = useState("");
  const [flowLogs, setFlowLogs] = useState<string[]>([]);
  const [jobLogs, setJobLogs] = useState<Record<string, string[]>>({});
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [promptText, setPromptText] = useState("");
  const [results, setResults] = useState<Record<string, { answer?: string; error?: string }>>({});
  const [cachedAt, setCachedAt] = useState<string | null>(null);
  // 盘前两路均未回复时置 true：停在流程展示页，不退化生成/展示结论
  const [halted, setHalted] = useState(false);
  // 正在为该目标打开登录浏览器
  const [relogining, setRelogining] = useState<string | null>(null);
  // 手动模式：不依赖网页 LLM 自动化，直接粘贴各路回复，走项目 LLM 综合
  const [manualOpen, setManualOpen] = useState(false);
  const [manualLogs, setManualLogs] = useState<string[]>([]);
  // 完整结论弹窗：结论过长时仅预览前段，按钮弹出查看全文
  const [showFullConclusion, setShowFullConclusion] = useState(false);
  // 过程数据（提示词/各路回答/进度日志）仅分析中展示；最终结果落 localStorage 时仍需 ref 同步最新值
  const resultsRef = useRef<Record<string, { answer?: string; error?: string }>>({});
  const flowLogsRef = useRef<string[]>([]);

  const CACHE_KEY = `${isPreview ? "preview" : isVerify ? "verify" : "review"}_ai_${date}`;
  const PROMPT_EP = isPreview ? "/review/preview-prompt" : isVerify ? "/review/verify-prompt" : "/review/ai-prompt";
  const ANALYSIS_EP = isPreview ? "/review/preview-analysis" : isVerify ? "/review/verify-analysis" : "/review/ai-analysis";
  // 本地 md 文件（权威当天结果）：preview 有落盘；verify 当前无落盘，走 localStorage
  const REPORT_FILE_EP = isVerify ? "" : `/review/report?date=${date}&kind=${isPreview ? "preview" : "review"}`;

  // 打开弹窗（或切换日期）时：优先回显该日期上次跑过的结果，避免重跑（一次约 3 分钟、且会重复发给网页 LLM）
  useEffect(() => {
    if (!open) return;
    setError(null);
    setStage("");
    setRunning(false);
    setHalted(false);
    setShowFullConclusion(false);
    setJobLogs({});
    let cacheUsed = false;
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (raw) {
        const c = JSON.parse(raw);
        setPromptText(c.prompt ?? "");
        setResults(c.results ?? {});
        resultsRef.current = c.results ?? {};
        setReport(c.report ?? null);
        setFlowLogs(c.flowLogs ?? []);
        flowLogsRef.current = c.flowLogs ?? [];
        setCachedAt(c.cachedAt ?? null);
        cacheUsed = true;
      }
    } catch {
      /* 缓存损坏则忽略，按空状态处理 */
    }
    if (!cacheUsed) {
      setPromptText("");
      setResults({});
      resultsRef.current = {};
      setReport(null);
      setFlowLogs([]);
      flowLogsRef.current = [];
      setCachedAt(null);
      // 本地 md 是当日结果的权威来源：localStorage 无缓存时直接从文件回显，不重跑
      (async () => {
        if (!REPORT_FILE_EP) return;
        try {
          const f = await api.tools.get<{ exists: boolean; content?: string; mtime?: string }>(REPORT_FILE_EP);
          if (f?.exists && f.content) {
            setReport(f.content);
            setCachedAt(f.mtime ?? null);
          }
        } catch {
          /* 文件读取失败则保持空状态 */
        }
      })();
    }
  }, [open, date]);

  const saveCache = (p: string, reportText: string | null) => {
    const now = new Date().toLocaleString("zh-CN", { hour12: false });
    try {
      localStorage.setItem(
        CACHE_KEY,
        JSON.stringify({
          prompt: p,
          results: resultsRef.current,
          report: reportText,
          flowLogs: flowLogsRef.current,
          cachedAt: now,
        }),
      );
      setCachedAt(now);
    } catch {
      /* localStorage 不可用/满时静默降级，不影响主流程 */
    }
  };

  const ts = () => new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const appendFlow = (s: string) => {
    const line = `${ts()} ${s}`;
    flowLogsRef.current = [...flowLogsRef.current, line];
    setFlowLogs(flowLogsRef.current);
  };

  // 手动模式：加载发给各路的提示词原文（供手动复制）
  const loadPromptText = async () => {
    try {
      const pr = await api.tools.get<{ prompt: string }>(`${PROMPT_EP}?date=${date}`);
      setPromptText(pr.prompt || "");
      return pr.prompt || "";
    } catch (e: any) {
      throw new Error(e?.message ?? String(e));
    }
  };

  // 手动模式：把手动粘贴的各路回答交给项目 LLM 综合（后端同时落盘 md）
  const manualRun = async (answers: ManualAnswer[]) => {
    setManualLogs([]);
    try {
      const res = await api.tools.post<{ report?: string; logs?: string[]; error?: string }>(ANALYSIS_EP, { date, web_answers: answers });
      if (res?.error) throw new Error(res.error);
      const finalReport = res?.report || "（无返回内容）";
      setReport(finalReport);
      setManualLogs(res?.logs ?? []);
      // 落 localStorage：当天结果重开弹窗直接回显，不必每次重新分析
      const ansMap: Record<string, { answer: string }> = {};
      answers.forEach((a) => {
        ansMap[a.target] = { answer: a.answer };
      });
      setResults(ansMap);
      resultsRef.current = ansMap;
      saveCache(promptText, finalReport);
    } catch (e: any) {
      throw new Error(e?.message ?? String(e));
    }
  };

  const runOne = async (opt: { key: string; label: string }, prompt: string): Promise<string> => {
    appendFlow(`▶ 发送「${opt.label}」…`);
    try {
      const r = await askOne(
        { target: opt.key, prompt, timeout_s: 180 },
        { pollMs: 1200, onLogs: (_t, logs) => setJobLogs((prev) => ({ ...prev, [opt.key]: logs })) },
      );
      setResults((prev) => ({ ...prev, [opt.key]: { answer: r.answer } }));
      resultsRef.current[opt.key] = { answer: r.answer };
      appendFlow(`✓ ${opt.label} 完成（${r.answer.length} 字 / ${r.elapsed_s ?? "?"}s）`);
      return r.answer;
    } catch (e: any) {
      const msg = e?.message ?? String(e);
      // 失败原因也落到该路面板，便于定位（如豆包登录态失效/滑块验证）
      setResults((prev) => ({ ...prev, [opt.key]: { error: msg } }));
      resultsRef.current[opt.key] = { error: msg };
      appendFlow(`✗ ${opt.label} 失败：${msg}`);
      throw e;
    }
  };

  // 登录态失效时触发该目标的登录浏览器（后端弹出有头浏览器，登录后关闭即保存会话）
  const relogin = async (target: string) => {
    if (relogining) return;
    setRelogining(target);
    try {
      const res = await api.tools.post<{ ok: boolean; detail?: string }>("/llm-web/login", { target });
      appendFlow(`⇄ 已触发 ${target} 登录：${res?.detail ?? "请在弹窗中登录并关闭浏览器"}`);
    } catch (e: any) {
      appendFlow(`✗ ${target} 触发登录失败：${e?.message ?? String(e)}`);
    } finally {
      setRelogining(null);
    }
  };

  const run = async () => {
    if (running) return;
    setRunning(true);
    setReport(null);
    setError(null);
    setHalted(false);
    setShowFullConclusion(false);
    setFlowLogs([]);
    flowLogsRef.current = [];
    setJobLogs({});
    setResults({});
    resultsRef.current = {};
    setPromptText("");
    setCachedAt(null);
    // 验证闭环只走项目 LLM（MiMo），不并发问豆包/DeepSeek 网页
    if (isVerify) {
      setStage("MiMo 盘后验证中（早晨预演 vs 收盘核验）…");
      try {
        const res = await api.tools.post<any>(ANALYSIS_EP, { date, web_answers: [] });
        const finalReport = res.report || "（无返回内容）";
        setReport(finalReport);
        setStage("完成（项目 LLM 验证）");
        saveCache("", finalReport);
      } catch (e: any) {
        setError(e?.message ?? String(e));
        setStage("出错");
      } finally {
        setRunning(false);
      }
      return;
    }
    setStage(isPreview ? "获取盘前研判提示词…" : "获取综合实战版提示词…");
    let promptText = "";
    try {
      const pr = await api.tools.get<{ prompt: string }>(`${PROMPT_EP}?date=${date}`);
      const prompt = pr.prompt;
      promptText = prompt;
      // 拿到就展示原文，随后两路并发发送（用户可边等边核对发给 LLM 的内容）
      setPromptText(prompt);
      appendFlow(`· 提示词已就绪（${prompt.length} 字）`);
      setStage(`并发问 ${TARGET_LABELS}…`);
      const settled = await Promise.allSettled(
        TARGETS.map((opt) =>
          runOne(opt, prompt).then((answer) => ({ target: opt.key, label: opt.label, answer })),
        ),
      );
      const answers: { target: string; label: string; answer: string }[] = [];
      settled.forEach((r, i) => {
        if (r.status === "fulfilled") answers.push(r.value);
        else appendFlow(`✗ ${TARGETS[i].label} 失败：${String(r.reason)}`);
      });
      // 盘前：任一来源未收到回复则不完整，停在流程页，不生成/展示预演结论（避免缺少交叉验证）
      if (isPreview && answers.length < TARGETS.length) {
        setStage(`仅 ${answers.length}/${TARGETS.length} 路有回复，缺少交叉验证，未生成预演结论（可重试）`);
        saveCache(promptText, null);
        setHalted(true);
        setRunning(false);
        return;
      }
      // 综合前先落一次缓存：即便后续综合失败，已拿到的各路回答也不会丢
      saveCache(promptText, null);
      setStage(`综合 ${answers.length} 个来源…`);
      const res = await api.tools.post<any>(ANALYSIS_EP, { date, web_answers: answers });
      if (res.error) throw new Error(res.error);
      const finalReport = res.report || "（无返回内容）";
      setReport(finalReport);
      setStage(
        answers.length
          ? `完成（综合 ${answers.length} 源）`
          : isPreview
            ? "完成（本地数据 AI 预演）"
            : "完成（本地数据 AI 复盘）",
      );
      saveCache(promptText, finalReport);
    } catch (e: any) {
      setError(e?.message ?? String(e));
      setStage("出错");
      // 出错也保留已拿到的部分（如豆包失败但 DeepSeek 成功）
      if (promptText) saveCache(promptText, null);
    } finally {
      setRunning(false);
    }
  };

  if (!open) return null;
  return (
    <>
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-card border rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold">
            {isPreview
              ? `AI 今日预演（${date} · ${TARGET_LABELS} 综合）`
              : `AI 多源复盘（${date} · ${TARGET_LABELS} 综合）`}
          </h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">
            ×
          </button>
        </div>
        <div className="p-4 overflow-y-auto space-y-3">
          <div className="flex items-center gap-2">
            <button
              onClick={run}
              disabled={running}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50"
            >
              {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
              {running ? "分析中…" : cachedAt ? "重新分析" : isPreview ? "开始 AI 预演" : "开始 AI 复盘"}
            </button>
            <span className="text-xs text-muted-foreground">{stage}</span>
            {cachedAt && !running && (
              <span className="text-xs text-muted-foreground">
                · 已回显 {cachedAt} 的结果（重跑会重新发给 {TARGET_LABELS}）
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setManualOpen((v) => !v)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted"
            >
              {manualOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <Clipboard className="h-3.5 w-3.5" />}
              手动多源分析
            </button>
            <span className="text-xs text-muted-foreground">粘贴豆包/DeepSeek 回复 · 项目 LLM 综合</span>
          </div>

          {manualOpen && (
            <div className="space-y-2">
              <LLMManualPaste
                sources={TARGETS}
                prompt={promptText}
                onGetPrompt={loadPromptText}
                onSubmit={manualRun}
                initial={TARGETS.map((t) =>
                  results[t.key]?.answer ? { target: t.key, label: t.label, answer: results[t.key].answer } : null,
                ).filter((x): x is ManualAnswer => x !== null)}
                hint={`粘贴 ${TARGET_LABELS} 的回复后点「分析」，由项目 LLM 综合（后端同时落盘 md）`}
              />
              {manualLogs.length > 0 && (
                <details open>
                  <summary className="cursor-pointer select-none text-[11px] font-medium text-muted-foreground">
                    LLM 分析过程（{manualLogs.length} 条）
                  </summary>
                  <pre className="text-[10px] font-mono bg-muted/40 rounded p-2 max-h-48 overflow-y-auto whitespace-pre-wrap text-muted-foreground mt-1">
                    {manualLogs.join("\n")}
                  </pre>
                </details>
              )}
            </div>
          )}

          {(running || halted) && (
            <>
              {/* 实际发给各路 LLM 的提示词原文（各路内容相同） */}
              {promptText && (
                <details open className="rounded border bg-muted/20">
                  <summary className="cursor-pointer select-none text-xs font-medium px-2 py-1.5">
                    发送给 {TARGET_LABELS} 的提示词原文（{promptText.length} 字，各路相同）
                  </summary>
                  <pre className="text-[11px] font-mono leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap px-2 pb-2">
{promptText}
                  </pre>
                </details>
              )}

              {/* 各路各自的实时进度日志 */}
              <div className={cn("grid gap-2 sm:grid-cols-2", TARGETS.length >= 3 && "lg:grid-cols-3")}>
                {TARGETS.map((opt) => (
                  <div key={opt.key} className="rounded border bg-muted/30 p-2">
                    <p className="text-xs font-medium mb-1 flex items-center gap-1">
                      {running && !jobLogs[opt.key]?.length ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                      {opt.label} 实时进度
                    </p>
                    <pre className="text-[11px] font-mono leading-relaxed max-h-44 overflow-y-auto whitespace-pre-wrap text-muted-foreground">
{((jobLogs[opt.key] || []) as string[]).join("\n") || (running ? "等待提交…" : "—")}
                    </pre>
                  </div>
                ))}
              </div>

              {/* 各路收到的回答（完成后即时展示，不等综合） */}
              {Object.keys(results).length > 0 && (
                <div className={cn("grid gap-2 sm:grid-cols-2", TARGETS.length >= 3 && "lg:grid-cols-3")}>
                  {TARGETS.map((opt) => {
                    const r = results[opt.key];
                    if (!r) return null;
                    return (
                      <div key={opt.key} className="rounded border p-2">
                        <p className="text-xs font-medium mb-1 flex items-center gap-1">
                          {opt.label} 的回答
                          {r.answer ? `（${r.answer.length} 字）` : ""}
                          {running && !r.answer && !r.error ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                        </p>
                        {r.error ? (
                          <div>
                            <p className="text-[11px] text-red-500 whitespace-pre-wrap">{r.error}</p>
                            {/登录|login|解锁更多功能|会话/.test(r.error) && (
                              <button
                                onClick={() => relogin(opt.key)}
                                disabled={relogining !== null}
                                className="mt-1.5 flex items-center gap-1 px-2 py-1 text-xs border rounded-md hover:bg-muted disabled:opacity-50"
                              >
                                {relogining === opt.key ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <RefreshCw className="h-3 w-3" />
                                )}
                                重新登录 {opt.label} 并重试
                              </button>
                            )}
                          </div>
                        ) : (
                          <div className="prose prose-sm prose-invert max-w-none max-h-80 overflow-y-auto text-foreground">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.answer || "（空回答）"}</ReactMarkdown>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* 主流程日志（带时间戳） */}
              {flowLogs.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-1">主流程</p>
                  <pre className="text-[11px] font-mono bg-muted/50 rounded p-2 max-h-28 overflow-y-auto whitespace-pre-wrap">
{flowLogs.join("\n")}
                  </pre>
                </div>
              )}
            </>
          )}

          {error && <p className="text-xs text-red-500 whitespace-pre-wrap">{error}</p>}
          {!running && !halted && report && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">
                {isPreview ? "最终综合预演" : "最终综合复盘"} · 结论
              </p>
              {(() => {
                const conclusion = extractConclusion(report);
                if (!conclusion) {
                  return (
                    <div className="prose prose-sm prose-invert max-w-none text-foreground">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
                    </div>
                  );
                }
                const long = conclusion.length > CONCLUSION_PREVIEW_LEN;
                return (
                  <>
                    <pre className="text-sm leading-relaxed text-foreground whitespace-pre-wrap font-sans">
                      {long ? conclusion.slice(0, CONCLUSION_PREVIEW_LEN) : conclusion}
                    </pre>
                    {long && (
                      <button
                        onClick={() => setShowFullConclusion(true)}
                        className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors"
                      >
                        <Maximize2 className="h-3.5 w-3.5" /> 查看完整结论（{conclusion.length} 字）
                      </button>
                    )}
                  </>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </div>

    {/* 完整结论弹窗：结论过长时点击「查看完整结论」打开，全文可滚动 */}
    {showFullConclusion && report && (
      <div
        className="fixed inset-0 bg-black/70 flex items-center justify-center z-[60] p-4"
        onClick={() => setShowFullConclusion(false)}
      >
        <div
          className="bg-card border rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between p-4 border-b">
            <h3 className="font-semibold">{isPreview ? "AI 今日预演" : "AI 复盘"} · 完整结论</h3>
            <button
              onClick={() => setShowFullConclusion(false)}
              className="text-muted-foreground hover:text-foreground text-xl leading-none"
            >
              ×
            </button>
          </div>
          <div className="p-4 overflow-y-auto">
            <pre className="text-sm leading-relaxed text-foreground whitespace-pre-wrap font-sans">
              {extractConclusion(report)}
            </pre>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

function PreMarketAIModal({
  date,
  fearGreedy,
  auctionCount,
  holdingsCount,
  prevReview,
  prevVibe,
  marketOneliner,
  directions,
  open,
  onClose,
  title = "盘前准备 · AI 询问",
}: {
  date: string;
  fearGreedy?: FlowStatus["pre"]["fear_greedy"] | null;
  auctionCount: number;
  holdingsCount: number;
  prevReview: boolean;
  prevVibe: boolean;
  marketOneliner?: string;
  directions?: VibeDirection[];
  open: boolean;
  onClose: () => void;
  title?: string;
}) {
  const { askOne } = useLLMWebAsk();
  const [flowLogs, setFlowLogs] = useState<string[]>([]);
  const flowLogsRef = useRef<string[]>([]);
  const [jobLogs, setJobLogs] = useState<Record<string, string[]>>({});
  const [results, setResults] = useState<Record<string, { answer?: string; error?: string }>>({});
  const resultsRef = useRef<Record<string, { answer?: string; error?: string }>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string>("");
  const [manualOpen, setManualOpen] = useState(false);

  const appendFlow = (m: string) => {
    flowLogsRef.current = [...flowLogsRef.current, m];
    setFlowLogs(flowLogsRef.current);
  };

  const buildPrompt = (): string => {
    const rows: string[] = [];
    rows.push("你是A股短线操盘手，请基于以下盘前数据做盘前准备。当前交易数据：");
    rows.push(`- 日期 ${date}`);
    if (fearGreedy) {
      rows.push(`- 恐惧贪婪指数 ${fearGreedy.afgi}（${fearGreedy.state}）`);
      if (fearGreedy.advice) rows.push(`- 情绪建议：${fearGreedy.advice}`);
    }
    rows.push(`- 昨日复盘：${prevReview ? "已生成" : "无"}；今日预演：${prevVibe ? "已生成" : "无"}`);
    if (marketOneliner) rows.push(`- 昨日 vibe 一句话市场判断：${marketOneliner}`);
    if (directions?.length) {
      rows.push("- 昨日 vibe 给出的方向：");
      directions.forEach((d, i) => rows.push(`  ${i + 1}. ${d.direction}（逻辑：${d.logic}）`));
    }
    rows.push(`- 竞价数据条数 ${auctionCount}；当前持仓 ${holdingsCount} 只`);
    rows.push("");
    rows.push("请按盘前清单逐项给出可执行建议：");
    rows.push("1. 外围（美股/韩日/新闻）影响");
    rows.push("2. 板块三问（高潮/超跌/预期差）");
    rows.push("3. 定周期/主线/候选池");
    rows.push("4. 每票定买点·止盈价·止损价");
    return rows.join("\n");
  };

  const runOne = async (opt: { key: string; label: string }, p: string): Promise<string> => {
    appendFlow(`▶ 发送「${opt.label}」…`);
    try {
      const r = await askOne(
        { target: opt.key, prompt: p, timeout_s: 180 },
        { pollMs: 1200, onLogs: (_t, logs) => setJobLogs((prev) => ({ ...prev, [opt.key]: logs })) },
      );
      setResults((prev) => ({ ...prev, [opt.key]: { answer: r.answer } }));
      resultsRef.current[opt.key] = { answer: r.answer };
      appendFlow(`✓ ${opt.label} 完成（${r.answer.length} 字 / ${r.elapsed_s ?? "?"}s）`);
      return r.answer;
    } catch (e: any) {
      const msg = e?.message ?? String(e);
      setResults((prev) => ({ ...prev, [opt.key]: { error: msg } }));
      resultsRef.current[opt.key] = { error: msg };
      appendFlow(`✗ ${opt.label} 失败：${msg}`);
      throw e;
    }
  };

  const run = async () => {
    if (running) return;
    setRunning(true);
    setError(null);
    setFlowLogs([]);
    flowLogsRef.current = [];
    setJobLogs({});
    setResults({});
    resultsRef.current = {};
    const p = buildPrompt();
    setPrompt(p);
    appendFlow(`· 盘前提示词已就绪（${p.length} 字）`);
    try {
      await Promise.allSettled(
        REVIEW_LLM.map((opt) => runOne(opt, p)),
      );
      appendFlow(`· 完成（${REVIEW_LLM.filter((opt) => resultsRef.current[opt.key]?.answer).length}/${REVIEW_LLM.length} 路成功）`);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setRunning(false);
    }
  };

  if (!open) return null;
  // 手动模式：手动粘贴豆包/DeepSeek 回答并应用到逐路展示区（盘前无项目 LLM 综合步骤，仅并列展示两路）
  const applyManual = async (answers: ManualAnswer[]) => {
    const m: Record<string, { answer: string }> = {};
    answers.forEach((a) => {
      m[a.target] = { answer: a.answer };
    });
    setResults((prev) => ({ ...prev, ...m }));
    resultsRef.current = { ...resultsRef.current, ...m };
    appendFlow(`· 手动粘贴【${answers.map((a) => a.label).join(" + ")}】回答已应用（${answers.length} 路）`);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="bg-card border rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold">{title}（{date}）</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">
            ×
          </button>
        </div>
        <div className="p-4 overflow-y-auto space-y-3">
          <div className="flex items-center gap-2">
            <button
              onClick={run}
              disabled={running}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50"
            >
              {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
              {running ? "询问中…" : "开始询问豆包 / DeepSeek"}
            </button>
            <button
              onClick={() => setManualOpen((v) => !v)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors"
            >
              {manualOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <Clipboard className="h-3.5 w-3.5" />}
              手动多源分析
            </button>
            <span className="text-xs text-muted-foreground">粘贴豆包/DeepSeek 回复 · 并列展示</span>
          </div>

          {manualOpen && (
            <LLMManualPaste
              sources={REVIEW_LLM}
              prompt={prompt}
              onGetPrompt={async () => {
                const p = buildPrompt();
                setPrompt(p);
                return p;
              }}
              onSubmit={applyManual}
              actionLabel="应用回答"
              initial={REVIEW_LLM.map((t) =>
                results[t.key]?.answer ? { target: t.key, label: t.label, answer: results[t.key].answer } : null,
              ).filter((x): x is ManualAnswer => x !== null)}
              hint="手动粘贴豆包/DeepSeek 回答后点「应用回答」，展开到上方逐路展示（盘前不做项目 LLM 综合）"
            />
          )}

          {prompt && (
            <details open className="rounded border bg-muted/20">
              <summary className="cursor-pointer select-none text-xs font-medium px-2 py-1.5">
                发送给豆包 / DeepSeek 的提示词原文（{prompt.length} 字，两路相同）
              </summary>
              <pre className="text-[11px] font-mono leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap px-2 pb-2">
{prompt}
              </pre>
            </details>
          )}

          <div className="grid gap-2 sm:grid-cols-2">
            {REVIEW_LLM.map((opt) => (
              <div key={opt.key} className="rounded border bg-muted/30 p-2">
                <p className="text-xs font-medium mb-1 flex items-center gap-1">
                  {running && !jobLogs[opt.key]?.length ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                  {opt.label} 实时进度
                </p>
                <pre className="text-[11px] font-mono leading-relaxed max-h-44 overflow-y-auto whitespace-pre-wrap text-muted-foreground">
{((jobLogs[opt.key] || []) as string[]).join("\n") || (running ? "等待提交…" : "—")}
                </pre>
              </div>
            ))}
          </div>

          {Object.keys(results).length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {REVIEW_LLM.map((opt) => {
                const r = results[opt.key];
                if (!r) return null;
                return (
                  <div key={opt.key} className="rounded border p-2">
                    <p className="text-xs font-medium mb-1 flex items-center gap-1">
                      {opt.label} 的回答
                      {r.answer ? `（${r.answer.length} 字）` : ""}
                      {running && !r.answer && !r.error ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    </p>
                    {r.error ? (
                      <p className="text-[11px] text-red-500 whitespace-pre-wrap">{r.error}</p>
                    ) : (
                      <div className="prose prose-sm prose-invert max-w-none max-h-80 overflow-y-auto text-foreground">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.answer || "（空回答）"}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {flowLogs.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">主流程</p>
              <pre className="text-[11px] font-mono bg-muted/50 rounded p-2 max-h-28 overflow-y-auto whitespace-pre-wrap">
{flowLogs.join("\n")}
              </pre>
            </div>
          )}

          {error && <p className="text-xs text-red-500 whitespace-pre-wrap">{error}</p>}
        </div>
      </div>
    </div>
  );
}

function HoldingsPanel({ portfolios, onReload, date }: { portfolios: Portfolio[]; onReload: () => void; date?: string }) {
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ alerts: Alert[]; wecom_pushed: boolean } | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiByCode, setAiByCode] = useState<Record<string, AiPosition>>({});

  // 进入页面时回显当天已缓存的 MiMo 持仓分析（不必重跑）
  useEffect(() => {
    if (!date) return;
    let alive = true;
    api.tools
      .get<{ ok: boolean; positions?: AiPosition[]; cached?: boolean }>(`/flow/analyze?date=${date}`)
      .then((res) => {
        if (!alive || !res?.positions?.length) return;
        const map: Record<string, AiPosition> = {};
        res.positions.forEach((p) => {
          map[p.code] = p;
        });
        setAiByCode(map);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [date]);

  const key = (code: string, kind: string) => `${kind}::${code}`;

  const setTarget = async (code: string, kind: "take_profit" | "stop_loss", price?: number) => {
    const k = key(code, kind);
    const value = price ?? parseFloat(targets[k]);
    if (!value || Number.isNaN(value)) return;
    setSaving(k);
    try {
      await api.tools.post(`/flow/target`, { code, price: value, kind });
      setTargets((t) => ({ ...t, [k]: "" }));
      await onReload();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setSaving(null);
    }
  };

  const setTargetRaw = async (code: string, kind: "take_profit" | "stop_loss", price: number) => {
    const k = key(code, kind);
    setSaving(k);
    try {
      await api.tools.post(`/flow/target`, { code, price, kind });
      await onReload();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setSaving(null);
    }
  };

  const runAi = async () => {
    if (analyzing) return;
    setAnalyzing(true);
    setAiError(null);
    try {
      const res = await api.tools.post<{ ok: boolean; positions?: AiPosition[]; error?: string }>(`/flow/analyze`);
      if (res?.error) throw new Error(res.error);
      const map: Record<string, AiPosition> = {};
      (res.positions ?? []).forEach((p) => {
        map[p.code] = p;
      });
      setAiByCode(map);
    } catch (e: any) {
      setAiError(e?.message ?? String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const runStops = async () => {
    setRunning(true);
    try {
      const res = await api.tools.post<{ ok: boolean; alerts: Alert[]; wecom_pushed: boolean; holdings: Portfolio[] }>(`/flow/stops`);
      setResult({ alerts: res.alerts ?? [], wecom_pushed: !!res.wecom_pushed });
      await onReload();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setRunning(false);
    }
  };

  const positions = portfolios.flatMap((pf) => pf.positions);
  const liveAlerts = portfolios.flatMap((pf) => pf.alerts);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={runStops}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          运行止盈/止损检查
        </button>
        <button
          onClick={runAi}
          disabled={analyzing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
          {analyzing ? "MiMo 分析持仓中…" : "AI 分析持仓（MiMo）"}
        </button>
      </div>

      {aiError && <p className="text-xs text-red-500 whitespace-pre-wrap">{aiError}</p>}

      {result && (
        <div className={cn("rounded-lg border p-3 text-sm", result.alerts.length ? "bg-orange-500/5 border-orange-500/30" : "bg-muted/40")}>
          {result.alerts.length ? (
            <>
              <p className="font-medium flex items-center gap-1.5 text-orange-600">
                <Bell className="h-4 w-4" /> {result.alerts.length} 条止盈/止损告警{result.wecom_pushed && "（已推企业微信）"}
              </p>
              <ul className="mt-1 space-y-1 text-xs">
                {result.alerts.map((a, i) => (
                  <li key={i} className="text-muted-foreground">
                    {a.name}({a.code})：{a.reason}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-muted-foreground text-xs">检查完成：无止盈/止损告警{result.wecom_pushed && "（已推企业微信）"}</p>
          )}
        </div>
      )}

      {liveAlerts.length > 0 && !result && (
        <div className="rounded-lg border border-orange-500/30 bg-orange-500/5 p-3 space-y-1">
          {liveAlerts.map((a, i) => (
            <p key={i} className="text-xs text-orange-600">
              ● {a.name}：{a.reason}
            </p>
          ))}
        </div>
      )}

      {positions.length === 0 ? (
        <p className="text-xs text-muted-foreground">自选股中没有持仓股</p>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground border-b bg-muted/30">
                <th className="py-2 px-3 font-medium">标的</th>
                <th className="py-2 px-3 font-medium">现价/成本</th>
                <th className="py-2 px-3 font-medium">盈亏</th>
                <th className="py-2 px-3 font-medium">止盈价</th>
                <th className="py-2 px-3 font-medium">止损价</th>
                <th className="py-2 px-3 font-medium">AI 解读</th>
                <th className="py-2 px-3 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const pnlOk = p.pnl_pct != null;
                const ai = aiByCode[p.code];
                return (
                  <tr key={p.code} className="border-b last:border-0">
                    <td className="py-2 px-3">
                      <span className="font-medium">{p.name}</span>
                      <span className="text-muted-foreground ml-1">{p.code}</span>
                    </td>
                    <td className="py-2 px-3 tabular-nums">
                      {p.current_price ? p.current_price.toFixed(2) : "—"}
                      <span className="text-muted-foreground"> / {p.cost_price ? p.cost_price.toFixed(2) : "—"}</span>
                    </td>
                    <td className={cn("py-2 px-3 tabular-nums", !pnlOk ? "text-muted-foreground" : p.pnl_pct! >= 0 ? "text-danger" : "text-success")}>
                      {pnlOk ? `${p.pnl_pct! >= 0 ? "+" : ""}${p.pnl_pct!.toFixed(2)}%` : "—"}
                    </td>
                    {(["take_profit", "stop_loss"] as const).map((kind) => {
                      const k = key(p.code, kind);
                      const suggested = kind === "take_profit" ? ai?.take_profit_suggestion : ai?.stop_loss_suggestion;
                      return (
                        <td key={kind} className="py-2 px-3">
                          <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-1">
                              <input
                                type="number"
                                step="0.01"
                                placeholder={p[kind] != null ? String(p[kind]) : "—"}
                                value={targets[k] ?? ""}
                                onChange={(e) => setTargets((t) => ({ ...t, [k]: e.target.value }))}
                                className="w-20 px-1.5 py-0.5 text-xs border rounded bg-background"
                              />
                              <button
                                onClick={() => setTarget(p.code, kind)}
                                disabled={saving === k}
                                className="px-2 py-0.5 text-xs border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                              >
                                {saving === k ? <Loader2 className="h-3 w-3 animate-spin" /> : <Target className="h-3 w-3" />}
                              </button>
                            </div>
                            {suggested != null && (
                              <button
                                onClick={() => setTargetRaw(p.code, kind, suggested)}
                                disabled={saving === k}
                                className="text-[10px] text-left text-muted-foreground hover:text-foreground hover:underline"
                              >
                                AI建议 {suggested.toFixed(2)}
                              </button>
                            )}
                          </div>
                        </td>
                      );
                    })}
                    <td className="py-2 px-3 max-w-[14rem]">
                      {ai ? (
                        <div className="space-y-0.5">
                          <p className="text-muted-foreground">{ai.comment || "—"}</p>
                          {ai.alert_reason ? <p className="text-orange-600 text-[10px]">{ai.alert_reason}</p> : null}
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-[10px]">{analyzing ? "分析中…" : "—"}</span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-muted-foreground max-w-[10rem]">
                      {p.note ? <span className="line-clamp-2">{p.note}</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const localToday = () => {
  const x = new Date();
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};

export function ShortTermFlow() {
  const today = localToday();
  const [date, setDate] = useState(today);
  const [status, setStatus] = useState<FlowStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [preVerify, setPreVerify] = useState<PreVerify | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preAskOpen, setPreAskOpen] = useState(false);
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const [previewRefresh, setPreviewRefresh] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.tools.get<FlowStatus>(`/flow/status?date=${date}`);
      setStatus(res);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [date]);

  const loadPreVerify = useCallback(async () => {
    try {
      const res = await api.tools.get<PreVerify>(`/flow/pre-verify?date=${date}`);
      setPreVerify(res);
    } catch (e: any) {
      setPreVerify(null);
    }
  }, [date]);

  useEffect(() => {
    load();
    loadPreVerify();
  }, [load, loadPreVerify]);

  const collectAuction = async () => {
    setCollecting(true);
    try {
      await api.tools.post(`/auction/collect`);
      await load();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setCollecting(false);
    }
  };

  const alertsCount = (status?.holdings ?? []).reduce((n, pf) => n + pf.alerts.length, 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Crosshair className="h-5 w-5 text-violet-500" /> 短线全流程
        </h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-2 py-1 text-sm border rounded-md bg-background"
          />
          <button onClick={() => load()} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
        </div>
      </div>

      {/* 一句话串联 */}
      <p className="text-xs text-muted-foreground -mt-2">
        盘前选好票 → 竞价后豆包/DeepSeek+多源综合出方案 → 盘中验资金→验合力→验龙头 → 执行计划内那一笔 → 持仓达标止盈止损即推企业微信 → 盘后复盘核验 → 明天继续。
      </p>

      {loading && !status ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" />
          <p className="text-xs">加载全流程状态…</p>
        </div>
      ) : error && !status ? (
        <div className="border rounded-lg p-12 text-center text-sm text-destructive">加载失败: {error}</div>
      ) : status ? (
        <>
          {/* 阶段状态条 */}
          <div className="flex flex-wrap gap-2 text-xs">
            <span className={cn(chip(true), "flex items-center gap-1")}>
              <Sun className="h-3.5 w-3.5" /> 盘前：{status.pre.fear_greedy?.state ?? "—"}
            </span>
            <span className={chip(status.auction.exists)}>
              <BarChart3 className="h-3.5 w-3.5 inline mr-0.5" /> 竞价：{status.auction.exists ? `${status.auction.count} 条` : "无"}
            </span>
            <span className={chip(alertsCount === 0)}>
              <Bell className="h-3.5 w-3.5 inline mr-0.5" /> 持仓告警 {alertsCount} 条
            </span>
            <span className={chip(status.post.review)}>
              <FileText className="h-3.5 w-3.5 inline mr-0.5" /> 复盘：{status.post.review ? "已生成" : "无"}
            </span>
            <span className={chip(status.post.vibe)}>
              <Brain className="h-3.5 w-3.5 inline mr-0.5" /> 明日预演：{status.post.vibe ? "已生成" : "无"}
            </span>
          </div>

          {/* 盘前 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={Sun} title="盘前准备" time="阶段〇 · T-1盘后 + 09:15 前" color="text-orange-500" />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">恐惧贪婪指数（最近）</p>
                <p className="mt-1 text-lg font-bold">
                  {status.pre.fear_greedy ? `${status.pre.fear_greedy.afgi} · ${status.pre.fear_greedy.state}` : "—"}
                </p>
                <p className="text-xs text-muted-foreground">{status.pre.fear_greedy?.date ?? "未更新"}</p>
                {status.pre.fear_greedy?.advice && (
                  <p className="mt-1.5 text-xs text-primary leading-snug border-t pt-1.5">
                    {status.pre.fear_greedy.advice}
                  </p>
                )}
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">昨日复盘（{status.pre.prev_bizday}）</p>
                <p className="mt-1 text-xs text-muted-foreground">盘后 AI 复盘（豆包 + DeepSeek 多源综合）的结论</p>
                <ReviewAIResultPreview date={status.pre.prev_bizday} />
                <Link
                  to={`/daily-review?date=${status.pre.prev_bizday}`}
                  className="mt-1.5 text-xs text-muted-foreground hover:underline inline-block"
                >
                  查看本地已有报告 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">今日预演（{status.date}）</p>
                <p className="mt-1 text-xs text-muted-foreground">由 {status.pre.prev_bizday} 盘后生成，供今日盘前参考</p>
                <p className={cn("mt-1 text-sm font-medium", status.pre.prev_vibe ? "text-green-600" : "text-muted-foreground")}>
                  {status.pre.prev_vibe ? "已生成" : "未生成"}
                </p>
                <ReviewAIResultPreview
                  key={`preview-${previewRefresh}`}
                  date={status.date}
                  kind="preview"
                  emptyText="今日暂无 AI 预演结果：先做一次（可复制提示词手动双源）"
                />
                <button
                  onClick={() => setPreviewOpen(true)}
                  className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors w-full justify-center"
                >
                  <Brain className="h-3.5 w-3.5" /> AI 预演（豆包+DeepSeek）
                </button>
                <Link to="/vibe-review" className="mt-1 text-xs text-primary hover:underline inline-block">
                  查看今日关注点 →
                </Link>
              </div>
            </div>
          </div>

          {/* 竞价后 + 盘中 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader
              icon={AlarmClock}
              title="竞价后 + 盘中验证"
              time="阶段一~四 · 09:25-10:00"
              color="text-emerald-500"
              right={
                <div className="flex flex-wrap gap-2">
                  {status.is_today && (
                    <button
                      onClick={collectAuction}
                      disabled={collecting}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      {collecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
                      采集竞价
                    </button>
                  )}
                </div>
              }
            />
            <p className="text-xs text-muted-foreground">
              竞价后四阶段规则验证资金态度与主线合力；AI 多源分析（豆包 + DeepSeek 综合）已内联在下方：
            </p>
            <AuctionSentiment date={date} />
          </div>

          {/* 持仓监控 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={Target} title="持仓监控" time="贯穿 · 止盈/止损达标即推企业微信" color="text-rose-500" />
            <HoldingsPanel portfolios={status.holdings} onReload={load} date={date} />
          </div>

          {/* 盘后 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={CalendarClock} title="盘后复盘" time="阶段五 · 15:00 后" color="text-blue-500" />
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">复盘报告（{status.date}）</p>
                <p className={cn("mt-1 text-sm font-medium", status.post.review ? "text-green-600" : "text-muted-foreground")}>
                  {status.post.review ? "已生成" : "未生成"}
                </p>
                {/* 本地 LLM 复盘综合结论（按日期从 md 文件读取；重开分析弹窗后 key 变化触发重新读取） */}
                <ReviewAIResultPreview
                  key={`post-${reviewRefresh}`}
                  date={status.date}
                  emptyText="结果未生成：点击下方「AI 复盘」运行后，此处展示综合结论"
                />
                <button
                  onClick={() => setReviewOpen(true)}
                  className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors w-full justify-center"
                >
                  <Brain className="h-3.5 w-3.5" /> AI 复盘（豆包+DeepSeek）
                </button>
                <Link to={`/daily-review?date=${status.date}`} className="mt-1.5 text-xs text-primary hover:underline inline-block">
                  查看复盘 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">验证闭环</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  早晨预演 vs 收盘结果逐条核验（成立/不成立/数据不足），次日复盘自动对账，结论落盘到 vibe reflection
                </p>
                <button
                  onClick={() => setVerifyOpen(true)}
                  className="mt-2 flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors w-full justify-center"
                >
                  <CheckCircle2 className="h-3.5 w-3.5" /> AI 验证（项目 LLM）
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}
      <ReviewAIModal
        date={status?.date ?? date}
        open={reviewOpen}
        onClose={() => {
          setReviewOpen(false);
          setReviewRefresh((n) => n + 1);
        }}
      />
      <ReviewAIModal
        date={status?.date ?? date}
        open={previewOpen}
        onClose={() => {
          setPreviewOpen(false);
          setPreviewRefresh((n) => n + 1);
        }}
        mode="preview"
      />
      <ReviewAIModal
        date={status?.date ?? date}
        open={verifyOpen}
        onClose={() => setVerifyOpen(false)}
        mode="verify"
      />
      <PreMarketAIModal
        date={date}
        fearGreedy={status?.pre.fear_greedy}
        auctionCount={status?.auction.count ?? 0}
        holdingsCount={status?.holdings.reduce((n, pf) => n + pf.positions.length, 0) ?? 0}
        prevReview={status?.pre.prev_review ?? false}
        prevVibe={status?.pre.prev_vibe ?? false}
        marketOneliner={preVerify?.predictions?.market_oneliner}
        directions={preVerify?.predictions?.directions}
        open={preAskOpen}
        onClose={() => setPreAskOpen(false)}
      />
    </div>
  );
}
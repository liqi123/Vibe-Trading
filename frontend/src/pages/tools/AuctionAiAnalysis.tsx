import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useLLMWebAsk } from "@/hooks/useLLMWebAsk";
import { LLMManualPaste, type ManualAnswer } from "@/components/llm/LLMManualPaste";
import { LLM_OPTIONS } from "@/lib/auctionAi";

interface WebAnswer {
  target: string;
  label: string;
  answer: string;
}

function todayStr() {
  const x = new Date();
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
}

/**
 * 集合竞价多源 AI 分析（与竞价看板「AI分析」tab 同源）。
 * 一键发送豆包 + DeepSeek → 取回两家回答 → 调 /auction/ai-analysis 做本地数据 + 双源综合。
 * 也可手动粘贴网页 LLM 回答后再分析（无回答则单源本地分析）。
 */
export function AuctionAiAnalysis({ date: propDate, onAnalyzed }: { date?: string; onAnalyzed?: (card: number, report: string) => void }) {
  const date = propDate || todayStr();
  const { askMany } = useLLMWebAsk();

  const [stage, setStage] = useState("auto");
  const [useFile, setUseFile] = useState(false);
  const [source, setSource] = useState<"ths_industry" | "ths_concept">("ths_industry");

  const [preview, setPreview] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewCacheRef = useRef<Record<string, { date: string; text: string }>>({});
  const previewReqRef = useRef(0);

  const [manualAnswers, setManualAnswers] = useState<ManualAnswer[]>([]);
  const [webAnswers, setWebAnswers] = useState<WebAnswer[]>([]);
  const [askLogs, setAskLogs] = useState<string[]>([]);
  const [askTarget, setAskTarget] = useState("");

  const [aiLoading, setAiLoading] = useState(false);
  const [aiReport, setAiReport] = useState("");
  const [aiError, setAiError] = useState("");
  const [aiLogs, setAiLogs] = useState<string[]>([]);

  const fetchAuctionStage = async (s?: string): Promise<string> => {
    try {
      const q = s && s !== "auto" ? `?stage=${s}` : "";
      const info = await api.tools.get<any>(`/llm-web/auction-prompt${q}`);
      return info?.stage ?? "";
    } catch {
      return "";
    }
  };

  const fetchAuctionPreview = useCallback(
    async (s?: string, force = false) => {
      if (!s || s === "auto") {
        setPreview("");
        return;
      }
      const cached = previewCacheRef.current[s];
      if (cached && cached.date === date && !force) {
        setPreview(cached.text);
        return;
      }
      setPreviewLoading(true);
      const reqId = ++previewReqRef.current;
      try {
        const dateQ = date ? `&date=${encodeURIComponent(date)}` : "";
        const info = await api.tools.get<any>(`/llm-web/auction-prompt?stage=${s}${dateQ}`);
        if (reqId === previewReqRef.current && info?.prompt) {
          previewCacheRef.current[s] = { date, text: info.prompt };
          setPreview(info.prompt);
        }
      } catch {
        /* ignore */
      } finally {
        if (reqId === previewReqRef.current) setPreviewLoading(false);
      }
    },
    [date],
  );

  // 挂载时静默预取 ①~④（仅暖缓存，不填充/发送），手动点选即可秒出
  useEffect(() => {
    ["0", "1", "2", "3"].forEach((s) => {
      api.tools
        .get<any>(`/llm-web/auction-prompt?stage=${s}`)
        .then((info) => {
          if (info?.prompt) previewCacheRef.current[s] = { date: "", text: info.prompt };
        })
        .catch(() => {});
    });
  }, []);

  useEffect(() => {
    fetchAuctionPreview(stage);
  }, [stage, fetchAuctionPreview]);

  const handleSendAll = async () => {
    if (stage === "auto") {
      toast.warning("请先在阶段下拉中选择具体阶段（①~④）后再一键发送");
      return;
    }
    const targets = LLM_OPTIONS;
    setAskTarget("all");
    setWebAnswers([]);
    const st = await fetchAuctionStage(stage);
    setAskLogs([
      `[${new Date().toLocaleTimeString()}] 开始一键发送 ${targets.map((t) => t.label).join(" + ")}${st ? `（${st}）` : ""}...`,
    ]);
    fetchAuctionPreview(stage);
    await askMany(
      targets.map((opt) => ({
        target: opt.key,
        label: opt.label,
        use_template: true,
        use_file: useFile,
        timeout_s: 120,
        stage: stage !== "auto" ? Number(stage) : undefined,
        date,
      })),
      {
        pollMs: 1500,
        onDone: (r) => {
          const label = targets.find((o) => o.key === r.target)?.label ?? r.target;
          if (r.error) {
            setWebAnswers((prev) => [...prev, { target: r.target, label, answer: `✗ ${label} 失败: ${r.error}` }]);
            setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ✗ ${label}: ${r.error}`]);
            toast.warning(`${label} 自动获取失败`);
          } else {
            setWebAnswers((prev) => [...prev, { target: r.target, label, answer: r.answer }]);
            setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ✓ ${label} 完成（${r.answer.length} 字）`]);
            // 自动落盘：该阶段该信源回答存成 md（data/auction_web_answers/{date}/stage{N}.md）
            api.tools
              .post("/llm-web/save-web-answer", { date, stage, target: r.target, label, answer: r.answer })
              .catch(() => {});
            toast.success(`${label} 回答已获取`);
          }
        },
      },
    );
    setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 全部完成`]);
    setAskTarget("");
  };

  const fetchAiAnalysis = async (extra: ManualAnswer[] = []) => {
    setAiLoading(true);
    setAiReport("");
    setAiError("");
    setAiLogs([]);
    const startedAt = Date.now();
    try {
      // 自动获取的 webAnswers 在前，手动粘贴在后，同一来源以手动为准
      const merged: ManualAnswer[] = [];
      const seen = new Set<string>();
      for (const w of [...webAnswers, ...extra]) {
        if (!w.answer || !w.answer.trim() || seen.has(w.target)) continue;
        seen.add(w.target);
        merged.push({ target: w.target, label: w.label, answer: w.answer.trim() });
      }
      const run = await api.tools.post<any>("/auction/ai-analysis/run", {
        date,
        concept_source: source === "ths_industry" ? "industry" : "concept",
        web_answers: merged,
        stage: stage !== "auto" ? Number(stage) : null,
      });
      if (!run?.task_id) throw new Error(run?.error || "任务启动失败");
      const taskId = run.task_id;
      // 轮询任务状态，实时展示 LLM 进度日志
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        const st = await api.tools.get<any>(`/auction/ai-analysis/status/${taskId}`);
        if (st?.logs?.length) setAiLogs(st.logs);
        if (st?.done) {
          const result = st.result || {};
          const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
          if (result.error) {
            setAiError(result.error);
            setAiLogs((prev) => [...prev, `✗ 分析失败（${elapsed}s）：${result.error}`]);
          } else {
            setAiReport(result.report || "");
            setAiLogs((prev) => [...prev, `✓ 分析完成（${elapsed}s）`]);
            if (result.saved) toast.success(`结果已保存：${result.saved}`);
            // 已落盘到某张阶段卡片时，即时合并到对应卡片显示（card = AI阶段下标 + 1）
            if (result.saved && onAnalyzed) onAnalyzed((Number(stage) ?? 0) + 1, result.report || "");
          }
          return;
        }
      }
    } catch (e: any) {
      setAiError(e?.message || String(e));
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <div className="rounded-lg bg-card border p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="font-semibold text-sm flex items-center gap-1.5">
          <Bot className="h-4 w-4 text-violet-500" /> AI 分析（豆包 + DeepSeek 多源综合）
        </h3>
        <div className="flex items-center gap-1 text-xs">
          {(["ths_industry", "ths_concept"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSource(s)}
              className={`px-2 py-1 rounded-md transition-colors ${
                source === s ? "bg-primary text-primary-foreground" : "bg-muted/40 text-muted-foreground hover:text-foreground"
              }`}
            >
              {s === "ths_industry" ? "行业" : "概念"}
            </button>
          ))}
        </div>
      </div>

      {/* 预览 + 阶段选择 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">将发送给豆包/DeepSeek 的内容（模板 + 本地实盘数据）</p>
          <div className="flex items-center gap-3">
            <button onClick={() => fetchAuctionPreview(stage, true)} className="text-xs text-muted-foreground hover:text-foreground">
              刷新
            </button>
            <button
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(preview || "");
                  toast.success("提示词已复制");
                } catch {
                  toast.error("复制失败（请手动选中复制）");
                }
              }}
              disabled={!preview}
              className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
              title={preview ? "复制上方提示词全文" : "请先在阶段下拉中选择具体阶段后点「刷新」加载提示词"}
            >
              复制提示词
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">阶段：</label>
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="text-sm border rounded-md px-2 py-1 bg-background"
          >
            <option value="auto">请选择阶段（手动）</option>
            <option value="0">① 盘前</option>
            <option value="1">② 09:25 情绪总开关</option>
            <option value="2">③ 09:35 验证资金态度</option>
            <option value="3">④ 09:45 确认主线合力</option>
          </select>
          <label
            className={`flex items-center gap-1 text-xs text-muted-foreground cursor-pointer ml-2 ${stage === "0" ? "opacity-50" : ""}`}
            title={stage === "0" ? "盘前不附文件" : "附带竞价数据 xlsx 作为附件"}
          >
            <input
              type="checkbox"
              checked={useFile}
              disabled={stage === "0"}
              onChange={(e) => setUseFile(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            传文件
          </label>
        </div>
        <textarea
          value={preview}
          readOnly
          placeholder={previewLoading ? "加载中…（正在从本地数据库 + 腾讯实时行情取数）" : "请先在上方选择阶段（①~④），预览将在此显示"}
          className="w-full h-48 p-3 text-xs font-mono border rounded-md bg-zinc-950 text-zinc-200 resize-y focus:outline-none"
        />
      </div>

      {/* 操作按钮 */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={handleSendAll}
          disabled={askTarget === "all"}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {askTarget === "all" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ExternalLink className="h-3.5 w-3.5" />
          )}
          一键发送（豆包 + DeepSeek）
        </button>
        <button
          onClick={() => fetchAiAnalysis(manualAnswers)}
          disabled={aiLoading}
          className="flex items-center gap-2 px-4 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
        >
          <Bot className={aiLoading ? "h-4 w-4 animate-pulse" : "h-4 w-4"} />
          {aiLoading ? "AI分析中..." : "开始AI分析"}
        </button>
      </div>

      {aiLoading && (
        <div className="border rounded-lg bg-zinc-950 text-zinc-300 font-mono text-xs p-3 max-h-56 overflow-y-auto space-y-0.5">
          {aiLogs.map((line, i) => (
            <div
              key={i}
              className={line.includes("✗") ? "text-red-400" : line.includes("✓") ? "text-emerald-400" : ""}
            >
              {line}
            </div>
          ))}
          <div className="animate-pulse text-zinc-500">▌ LLM 综合分析中...（约 40~90 秒）</div>
        </div>
      )}
      {!aiLoading && aiError && (
        <div className="border border-red-300 rounded-lg bg-red-50 dark:bg-red-950/20 p-4">
          <p className="text-sm text-red-600">
            <span className="font-medium">分析失败: </span>
            {aiError}
          </p>
        </div>
      )}
      {!aiLoading && aiReport && (
        <div className="border rounded-lg bg-card p-6">
          <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">{aiReport}</div>
        </div>
      )}
      {!aiLoading && !aiReport && !aiError && (
        <div className="border rounded-lg bg-card p-8 text-center text-muted-foreground">
          <Bot className="h-8 w-8 mx-auto mb-3 opacity-40" />
          <p className="text-sm">
            点击"开始AI分析"调用内置LLM（若已用"一键发送"收到豆包/DeepSeek回答，将自动综合两家观点）；或粘贴网页LLM回答后分析
          </p>
        </div>
      )}

      {/* 手动粘贴（通用模块：各来源独立粘贴框） */}
      <div className="border rounded-lg bg-card p-4 space-y-3">
        <p className="text-sm font-medium">网页LLM回答（手动粘贴）</p>
        <LLMManualPaste
          sources={LLM_OPTIONS.map((o) => ({ key: o.key, label: o.label }))}
          prompt={preview}
          onSubmit={(answers) => fetchAiAnalysis(answers)}
          onChange={(a) => setManualAnswers(a)}
          actionLabel="粘贴后综合"
          initial={webAnswers
            .filter((w) => w.answer && !w.answer.startsWith("✗"))
            .map((w) => ({ target: w.target, label: w.label, answer: w.answer }))}
          hint="从豆包/DeepSeek复制回答后粘贴到对应来源框，再点「粘贴后综合」（或直接点上方「开始AI分析」，两者都会并入已填回答）"
        />
      </div>

      {/* 自动获取的回答 */}
      {webAnswers.length > 0 && (
        <div className="space-y-3">
          {webAnswers.map((wa) => (
            <div key={wa.target} className="border rounded-lg bg-card p-4">
              <p className="text-xs font-medium text-muted-foreground mb-2">{wa.label} 回答</p>
              <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm">{wa.answer}</div>
            </div>
          ))}
        </div>
      )}

      {/* 进度日志 */}
      {askLogs.length > 0 && (
        <div className="border rounded-lg bg-zinc-950 text-zinc-300 font-mono text-xs p-3 max-h-48 overflow-y-auto">
          {askLogs.map((line, i) => (
            <div
              key={i}
              className={line.includes("✗") ? "text-red-400" : line.includes("✓") ? "text-emerald-400" : ""}
            >
              {line}
            </div>
          ))}
          {askTarget && <div className="animate-pulse text-zinc-500">▌ 运行中...</div>}
        </div>
      )}
    </div>
  );
}

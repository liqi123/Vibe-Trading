import { useEffect, useState } from "react";
import { Brain, Clipboard, Loader2, RefreshCw } from "lucide-react";

export interface ManualSource {
  key: string;
  label: string;
}

export interface ManualAnswer {
  target: string;
  label: string;
  answer: string;
}

/**
 * 通用「手动多源 LLM」面板 —— 用于所有走豆包/DeepSeek（及 Kimi）手动的短线流程组件。
 * - 每个来源一个粘贴框；填好后点「分析」把回答交给上游（项目 LLM 综合）或仅应用为回答。
 * - 提供可选的提示词展示/复制/获取（prompt + onGetPrompt）。
 * 用途示例：
 *   @example 综合模式（ReviewAIModal / AuctionAiAnalysis）
 *     <LLMManualPaste sources={[{key:'doubao',label:'豆包'},{key:'deepseek',label:'DeepSeek'}]}
 *       prompt={promptText} onGetPrompt={loadPromptText} onSubmit={manualRun} />
 *   @example 仅展示模式 / 需并入上游主分析按钮（PreMarketAIModal / AuctionAiAnalysis）
 *     onSubmit 不传时按钮隐藏；用 onChange 把实时答案上报，由上游「分析」按钮统一并入。
 */
export function LLMManualPaste({
  sources,
  prompt = "",
  onGetPrompt,
  onSubmit,
  onChange,
  actionLabel = "分析",
  hint,
  initial = [],
}: {
  sources: ManualSource[];
  prompt?: string;
  /** 点击「获取提示词」时的回调；返回的字符串会回填到提示词展示框 */
  onGetPrompt?: () => Promise<string> | string;
  /** 点击「分析」：把已填回答交给上游（项目 LLM 综合等）；返回后按钮结束 loading */
  onSubmit?: (answers: ManualAnswer[]) => Promise<void>;
  /** 任一粘贴框内容变化时上报当前已填回答（供上游「分析」按钮并入） */
  onChange?: (answers: ManualAnswer[]) => void;
  actionLabel?: string;
  hint?: string;
  /** 已有回答（上一次自动获取/缓存）预填到对应粘贴框，可再编辑，供复用/修改 */
  initial?: ManualAnswer[];
}) {
  const [texts, setTexts] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const a of initial) init[a.target] = a.answer;
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");

  const promptLabel = `发给 ${sources.map((s) => s.label).join(" / ")} 的提示词`;
  const filled: ManualAnswer[] = sources
    .map((s) => ({ target: s.key, label: s.label, answer: (texts[s.key] ?? "").trim() }))
    .filter((a) => a.answer);

  // 挂载时把预填回答上报一次，保证上游（如「开始AI分析」按钮）能看到已回显的回答
  useEffect(() => {
    onChange?.(
      sources
        .map((s) => {
          const a = initial.find((x) => x.target === s.key);
          return { target: s.key, label: s.label, answer: (a?.answer ?? "").trim() };
        })
        .filter((a) => a.answer),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setText = (s: ManualSource, v: string) => {
    setTexts((prev) => {
      const next = { ...prev, [s.key]: v };
      onChange?.(
        sources
          .map((x) => ({ target: x.key, label: x.label, answer: (next[x.key] ?? "").trim() }))
          .filter((a) => a.answer),
      );
      return next;
    });
  };

  const getPrompt = async () => {
    if (!onGetPrompt) return;
    setStage("获取提示词…");
    try {
      await onGetPrompt();
      setStage("提示词已就绪，可复制");
    } catch (e: any) {
      setStage("提示词获取失败：" + (e?.message ?? String(e)));
    }
  };

  const copyPrompt = async () => {
    if (!prompt) {
      setStage("提示词为空，请先获取");
      return;
    }
    try {
      await navigator.clipboard.writeText(prompt);
      setStage("提示词已复制");
    } catch {
      setStage("复制失败（请手动选中复制）");
    }
  };

  const handleSubmit = async () => {
    if (!onSubmit) return;
    if (!filled.length) {
      setStage("请至少粘贴一个来源的回答");
      return;
    }
    setBusy(true);
    setStage(`提交 ${filled.length} 个来源…`);
    try {
      await onSubmit(filled);
      setStage(`完成 · 已提交 ${filled.length} 个来源`);
    } catch (e: any) {
      setStage("提交失败：" + (e?.message ?? String(e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border bg-muted/10 p-3 space-y-2">
      {onGetPrompt && (
        <div className="rounded border bg-muted/20 p-2 space-y-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] font-medium">{promptLabel}</p>
            <div className="flex gap-1">
              <button
                onClick={copyPrompt}
                disabled={busy}
                className="flex items-center gap-1 text-[11px] border rounded px-1.5 py-0.5 hover:bg-muted disabled:opacity-50"
              >
                <Clipboard className="h-3 w-3" /> 复制提示词
              </button>
              <button
                onClick={getPrompt}
                disabled={busy}
                className="flex items-center gap-1 text-[11px] border rounded px-1.5 py-0.5 hover:bg-muted disabled:opacity-50"
              >
                <RefreshCw className="h-3 w-3" /> 获取提示词
              </button>
            </div>
          </div>
          <pre className="text-[11px] font-mono whitespace-pre-wrap max-h-40 overflow-y-auto text-muted-foreground">
            {prompt || "（暂无提示词：点「获取提示词」加载，或直接点上方开始按钮后自动填充）"}
          </pre>
        </div>
      )}

      <div className="space-y-2">
        {sources.map((s) => (
          <div key={s.key} className="space-y-1">
            <p className="text-[11px] font-medium text-muted-foreground">
              {s.label} 的回答（{texts[s.key]?.length ?? 0} 字）
            </p>
            <textarea
              placeholder={`粘贴 ${s.label} 的回复内容…`}
              value={texts[s.key] ?? ""}
              onChange={(e) => setText(s, e.target.value)}
              className="w-full min-h-[96px] rounded border bg-background p-2 text-xs font-mono whitespace-pre-wrap resize-y"
            />
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={handleSubmit}
          disabled={busy || !onSubmit}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50 transition-colors"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
          {busy ? "分析中…" : actionLabel}
        </button>
        {stage && <span className="text-xs text-muted-foreground">{stage}</span>}
        <span className="ml-auto text-[11px] text-muted-foreground">
          已填 {filled.length}/{sources.length} 个来源
        </span>
      </div>

      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
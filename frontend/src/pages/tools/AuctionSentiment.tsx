import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Signal {
  name: string;
  data: string;
  sig: "✅" | "❌" | "⚠️" | string;
  desc: string;
}
interface TopIndustry {
  industry: string;
  count: number;
  stocks: { code: string; name: string; chg: number }[];
}
interface StageResult {
  stage: number;
  time: string;
  signals?: Signal[];
  bad_count?: number;
  decision?: string;
  skip?: boolean;
  reason?: string;
  focused?: boolean;
  top_industries?: TopIndustry[];
  premium_ratio?: number;
  avg_now_premium?: number | null;
  now_negative?: number;
  total_lu?: number;
  mainline_industry?: string | null;
  top20?: { code: string; name: string; chg: number; industry: string }[];
  ai_report?: string;
  ai_source?: "project-llm" | "web-llm" | string;
}
interface CheckPayload {
  ok: boolean;
  error?: string;
  date: string;
  checked_at?: string;
  stage_reached?: number;
  stages: StageResult[];
  overall?: { verdict: string; bad_total: number; decisions: string[]; last_decision: string };
}

/** 阶段展示映射。后端 stage 编号 2/3/4/5 不动；显示编号从 1 起，对应竞价结束=阶段1。
 *  key: 后端 stage；value: { num: 阶段编号, label: 阶段描述, time: 时点 } */
const STAGE_DISPLAY: Record<number, { num: number; label: string; time: string }> = {
  2: { num: 1, label: "竞价结束", time: "09:25" },
  3: { num: 2, label: "验证资金态度", time: "09:35" },
  4: { num: 3, label: "主线合力", time: "09:45" },
  5: { num: 4, label: "选定个股", time: "10:00" },
};
const STAGE_NAMES_FALLBACK = ["盘前", "竞价结束", "验证资金态度", "主线合力", "选定个股"];

const decisionColor = (d: string) => {
  if (d === "可操作") return "bg-green-500/15 text-green-600 border-green-500/30";
  if (d === "防守") return "bg-orange-500/15 text-orange-600 border-orange-500/30";
  if (d === "空仓观望") return "bg-red-500/15 text-red-600 border-red-500/30";
  return "bg-yellow-500/15 text-yellow-600 border-yellow-500/30";
};

const verdictColor = (v: string) => decisionColor(v.includes("可操作") ? "可操作" : v.includes("防守") ? "防守" : v.includes("空仓") ? "空仓观望" : "观察");

/** 阶段分析结论。来源 project-llm=项目 LLM（本地+腾讯），web-llm=豆包+DeepSeek 网页版 */
function AiReportBlock({ text, source }: { text: string; source?: string }) {
  const isProject = source === "project-llm";
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        isProject ? "bg-sky-50 dark:bg-sky-950/20" : "bg-violet-50 dark:bg-violet-950/20",
      )}
    >
      <p
        className={cn(
          "text-xs font-semibold mb-2",
          isProject ? "text-sky-600 dark:text-sky-400" : "text-violet-600 dark:text-violet-400",
        )}
      >
        {isProject ? "项目 LLM 分析（本地竞价 + 腾讯实时）" : "AI 本地分析结论（豆包 + DeepSeek 多源综合）"}
      </p>
      <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm">{text}</div>
    </div>
  );
}

function StageCard({
  stage,
  generating,
  onGenerate,
}: {
  stage: StageResult;
  generating?: boolean;
  onGenerate?: (stage: number) => void;
}) {
  // 阶段 2/3/4/5（09:25 / 09:35 / 09:45 / 10:00）均走项目 LLM
  const isProjectLlm = (stage.stage ?? 0) >= 2;
  const display = STAGE_DISPLAY[stage.stage] || { num: stage.stage, label: stage.time || "", time: "" };
  return (
    <div className="rounded-lg bg-card border p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold text-sm">
          阶段{display.num} · {display.time} {display.label}
        </h3>
        {isProjectLlm && (
          <button
            onClick={() => onGenerate?.(stage.stage)}
            disabled={generating}
            className="ml-auto px-2 py-0.5 text-xs border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            {generating ? "分析中…" : stage.ai_report ? "重新分析" : "生成分析"}
          </button>
        )}
      </div>
      {stage.ai_report ? (
        <AiReportBlock text={stage.ai_report} source={stage.ai_source} />
      ) : (
        <p className="text-sm text-muted-foreground">
          {stage.skip
            ? stage.reason
            : isProjectLlm
              ? "点击「生成分析」：用项目 LLM 基于本地竞价数据 + 腾讯实时行情出结论，不经豆包/DeepSeek。"
              : "该阶段暂无结论：请点击下方按钮做豆包 + DeepSeek 多源综合分析，完成后自动显示在此。"}
        </p>
      )}
    </div>
  );
}

export function AuctionSentiment({ date: propDate }: { date?: string } = {}) {
  const x = new Date();
  const today = `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  const [date, setDate] = useState(propDate || today);
  const [payload, setPayload] = useState<CheckPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (propDate && propDate !== date) setDate(propDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propDate]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.tools.get<CheckPayload>(`/auction-sentiment/check?date=${date}`);
      setPayload(res);
      if (!res.ok && res.error) setError(res.error);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    load();
  }, [load]);

  // AI 分析落盘某张卡片后，即时合并到对应卡片显示（避免重拉全市场行情）
  const applyAiReport = useCallback((card: number, report: string, source = "project-llm") => {
    setPayload((prev) => {
      if (!prev) return prev;
      const stages = prev.stages ?? [];
      const idx = stages.findIndex((s) => s.stage === card);
      let newStages;
      if (idx >= 0) {
        newStages = stages.map((s) => (s.stage === card ? { ...s, ai_report: report, ai_source: source } : s));
      } else {
        newStages = [...stages, { stage: card, time: STAGE_DISPLAY[card]?.time || "", ai_report: report, ai_source: source }];
      }
      return { ...prev, stages: newStages };
    });
  }, []);

  // 阶段 2/3/4：项目 LLM 基于本地竞价 + 腾讯实时行情出分析（不经网页版）
  const [generating, setGenerating] = useState<number | null>(null);
  const [genError, setGenError] = useState<string | null>(null);
  const generateStage = useCallback(
    async (stage: number) => {
      setGenerating(stage);
      setGenError(null);
      try {
        const res = await api.tools.post<{ ok: boolean; narrative?: string; error?: string }>(
          "/auction-sentiment/stage-narrative",
          { date, stage, refresh: true },
        );
        if (res.ok && res.narrative) {
          applyAiReport(stage, res.narrative, "project-llm");
        } else {
          setGenError(res.error || "阶段分析生成失败");
        }
      } catch (e: any) {
        setGenError(e?.message ?? String(e));
      } finally {
        setGenerating(null);
      }
    },
    [date, applyAiReport],
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Activity className="h-5 w-5" /> 竞价情绪四阶段判断
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

      {loading ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" />
          <p className="text-xs">全市场行情拉取约需 10-20 秒…</p>
        </div>
      ) : error ? (
        <div className="border rounded-lg p-12 text-center">
          <p className="text-sm text-destructive">加载失败: {error}</p>
          <p className="mt-2 text-xs text-muted-foreground">请确认该日期已采集竞价数据（python -m data.auction_collector once）</p>
        </div>
      ) : (
        <>
          {/* 总判定（有overall时显示） */}
          {payload?.overall && (
            <div className="rounded-lg bg-card border p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs text-muted-foreground">{payload.date} {payload.checked_at} 综合判定</span>
                <span className={cn("px-3 py-1 text-base font-bold rounded-md border", verdictColor(payload.overall.verdict))}>
                  {payload.overall.verdict}
                </span>
                <span className="ml-auto flex flex-wrap gap-1">
                  {payload.overall.decisions.map((d, i) => {
                    const st = (payload.stages ?? [])[i];
                    const displayNum = st ? (STAGE_DISPLAY[st.stage]?.num ?? st.stage) : i + 1;
                    const label = STAGE_DISPLAY[st?.stage ?? -1]?.label || st?.time || STAGE_NAMES_FALLBACK[displayNum] || "";
                    return (
                      <span key={i} className={cn("px-2 py-0.5 text-xs rounded-full border", decisionColor(d))}>
                        阶段{displayNum}·{label} {d}
                      </span>
                    );
                  })}
                </span>
              </div>
            </div>
          )}

          {/* 四阶段卡片 — 始终渲染4张，有数据用真实，无数据用占位 */}
          <div className="grid gap-3 lg:grid-cols-2">
            {Object.entries(STAGE_DISPLAY).map(([stageKey, info]) => {
              const real = (payload?.stages ?? []).find((s) => s.stage === Number(stageKey));
              return (
                <StageCard
                  key={stageKey}
                  stage={real ?? {
                    stage: Number(stageKey),
                    time: info.time,
                    skip: true,
                    reason: payload?.stage_reached
                      ? `当前进度：阶段${payload.stage_reached}，该阶段待采集数据后生成`
                      : "等待竞价数据采集…",
                  }}
                  generating={generating === Number(stageKey)}
                  onGenerate={generateStage}
                />
              );
            })}
          </div>

          {genError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              阶段分析生成失败：{genError}
            </div>
          )}
        </>
      )}
    </div>
  );
}

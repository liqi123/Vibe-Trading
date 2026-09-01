import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AuctionAiAnalysis } from "./AuctionAiAnalysis";

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
}
interface CheckPayload {
  ok: boolean;
  error?: string;
  date: string;
  checked_at?: string;
  stages: StageResult[];
  overall?: { verdict: string; bad_total: number; decisions: string[]; last_decision: string };
}

const STAGE_NAMES = ["", "盘前", "09:25 竞价结束", "09:35 验证资金", "09:45 主线合力"];

const decisionColor = (d: string) => {
  if (d === "可操作") return "bg-green-500/15 text-green-600 border-green-500/30";
  if (d === "防守") return "bg-orange-500/15 text-orange-600 border-orange-500/30";
  if (d === "空仓观望") return "bg-red-500/15 text-red-600 border-red-500/30";
  return "bg-yellow-500/15 text-yellow-600 border-yellow-500/30";
};

const verdictColor = (v: string) => decisionColor(v.includes("可操作") ? "可操作" : v.includes("防守") ? "防守" : v.includes("空仓") ? "空仓观望" : "观察");

/** 本地 LLM 阶段分析结论（落盘 md 后由 check 接口挂到对应卡片） */
function AiReportBlock({ text }: { text: string }) {
  return (
    <div className="rounded-lg border bg-violet-50 dark:bg-violet-950/20 p-3">
      <p className="text-xs font-semibold text-violet-600 dark:text-violet-400 mb-2">
        AI 本地分析结论（豆包 + DeepSeek 多源综合）
      </p>
      <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm">{text}</div>
    </div>
  );
}

function StageCard({ stage }: { stage: StageResult }) {
  return (
    <div className="rounded-lg bg-card border p-4 space-y-3">
      <h3 className="font-semibold text-sm">
        阶段{stage.stage} · {stage.time}
      </h3>
      {stage.ai_report ? (
        <AiReportBlock text={stage.ai_report} />
      ) : (
        <p className="text-sm text-muted-foreground">
          {stage.skip
            ? stage.reason
            : "该阶段暂无 AI 综合结论：请点击下方按钮做本地 LLM 多源综合分析（豆包 + DeepSeek），完成后自动显示在此。"}
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
  const applyAiReport = useCallback((card: number, report: string) => {
    setPayload((prev) =>
      prev
        ? { ...prev, stages: (prev.stages ?? []).map((s) => (s.stage === card ? { ...s, ai_report: report } : s)) }
        : prev,
    );
  }, []);

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
      ) : payload?.overall ? (
        <>
          {/* 总判定 */}
          <div className="rounded-lg bg-card border p-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">{payload.date} {payload.checked_at} 综合判定</span>
              <span className={cn("px-3 py-1 text-base font-bold rounded-md border", verdictColor(payload.overall.verdict))}>
                {payload.overall.verdict}
              </span>
              <span className="ml-auto flex flex-wrap gap-1">
                {payload.overall.decisions.map((d, i) => (
                  <span key={i} className={cn("px-2 py-0.5 text-xs rounded-full border", decisionColor(d))}>
                    {STAGE_NAMES[i + 1]} {d}
                  </span>
                ))}
              </span>
            </div>
          </div>

          {/* 四阶段卡片 */}
          <div className="grid gap-3 lg:grid-cols-2">
            {(payload.stages ?? []).map((s) => (
              <StageCard key={s.stage} stage={s} />
            ))}
          </div>

          {/* AI 分析（豆包 + DeepSeek 多源综合） */}
          <AuctionAiAnalysis date={date} onAnalyzed={applyAiReport} />
        </>
      ) : (
        <div className="border rounded-lg p-12 text-center text-muted-foreground text-sm">无数据</div>
      )}
    </div>
  );
}

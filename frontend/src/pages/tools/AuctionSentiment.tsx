import { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw, Sparkles } from "lucide-react";
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
}
interface CheckPayload {
  ok: boolean;
  error?: string;
  date: string;
  checked_at?: string;
  stages: StageResult[];
  overall?: { verdict: string; bad_total: number; decisions: string[]; last_decision: string };
}

const STAGE_NAMES = ["", "09:25 竞价", "09:30 溢价", "09:35 主线", "09:45 确认"];

const decisionColor = (d: string) => {
  if (d === "可操作") return "bg-green-500/15 text-green-600 border-green-500/30";
  if (d === "防守") return "bg-orange-500/15 text-orange-600 border-orange-500/30";
  if (d === "空仓观望") return "bg-red-500/15 text-red-600 border-red-500/30";
  return "bg-yellow-500/15 text-yellow-600 border-yellow-500/30";
};

const verdictColor = (v: string) => decisionColor(v.includes("可操作") ? "可操作" : v.includes("防守") ? "防守" : v.includes("空仓") ? "空仓观望" : "观察");

const sigCls = (s: string) =>
  s === "✅" ? "text-green-600 font-bold" : s === "❌" ? "text-red-600 font-bold" : "text-yellow-600 font-bold";

function StageCard({ stage }: { stage: StageResult }) {
  if (stage.skip) {
    return (
      <div className="rounded-lg bg-card border p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">
            阶段{stage.stage} · {stage.time}
          </h3>
          <span className="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground">跳过</span>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{stage.reason}</p>
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-card border p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="font-semibold text-sm">
          阶段{stage.stage} · {stage.time}
        </h3>
        <span className={cn("px-2 py-0.5 text-xs font-medium rounded-full border", decisionColor(stage.decision ?? ""))}>
          {stage.decision}（坏信号 {stage.bad_count}）
        </span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b">
            <th className="py-1.5 pr-2 font-medium">检查项</th>
            <th className="py-1.5 pr-2 font-medium">数据</th>
            <th className="py-1.5 pr-2 font-medium w-8"></th>
            <th className="py-1.5 font-medium">说明</th>
          </tr>
        </thead>
        <tbody>
          {(stage.signals ?? []).map((s) => (
            <tr key={s.name} className="border-b last:border-0">
              <td className="py-1.5 pr-2 whitespace-nowrap">{s.name}</td>
              <td className="py-1.5 pr-2 tabular-nums">{s.data}</td>
              <td className={cn("py-1.5 pr-2", sigCls(s.sig))}>{s.sig === "✅" ? "✓" : s.sig === "❌" ? "✗" : "!"}</td>
              <td className="py-1.5 text-muted-foreground">{s.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* 阶段1：聚焦行业 */}
      {stage.top_industries && stage.top_industries.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-xs text-muted-foreground">高开TOP行业:</span>
          {stage.top_industries.map((t) => (
            <span key={t.industry} className="px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary">
              {t.industry} {t.count}只
            </span>
          ))}
          {!stage.focused && <span className="text-xs text-red-500">→ 未聚焦</span>}
        </div>
      )}

      {/* 阶段2：溢价明细 */}
      {stage.total_lu != null && (
        <p className="text-xs text-muted-foreground pt-1">
          昨日涨停 {stage.total_lu} 只 · 当前平均溢价{" "}
          <span className={cn("tabular-nums", (stage.avg_now_premium ?? 0) >= 0 ? "text-danger" : "text-success")}>
            {(stage.avg_now_premium ?? 0) >= 0 ? "+" : ""}
            {stage.avg_now_premium?.toFixed(2) ?? "—"}%
          </span>{" "}
          · 翻绿 {stage.now_negative} 只
        </p>
      )}

      {/* 阶段3：涨幅榜前20 */}
      {stage.top20 && stage.top20.length > 0 && (
        <details className="pt-1">
          <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
            涨幅榜前20（点击展开）
          </summary>
          <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-1">
            {stage.top20.map((s) => (
              <div key={s.code} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-muted/50">
                <span className="truncate">{s.name || s.code}</span>
                <span className="tabular-nums text-danger ml-1">+{Number(s.chg).toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export function AuctionSentiment({ date: propDate }: { date?: string } = {}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(propDate || today);
  const [stage, setStage] = useState(0);
  const [payload, setPayload] = useState<CheckPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [narrative, setNarrative] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    if (propDate && propDate !== date) setDate(propDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propDate]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNarrative(null);
    try {
      const res = await api.tools.get<CheckPayload>(
        `/auction-sentiment/check?date=${date}${stage ? `&stage=${stage}` : ""}`
      );
      setPayload(res);
      if (!res.ok && res.error) setError(res.error);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [date, stage]);

  useEffect(() => {
    load();
  }, [load]);

  const runNarrative = useCallback(
    async (force = false) => {
      setAiLoading(true);
      setAiError(null);
      try {
        const res = await api.tools.post<{ ok: boolean; narrative?: string; error?: string }>(
          `/auction-sentiment/narrative?date=${date}&refresh=${force}`,
          {}
        );
        if (!res.ok || !res.narrative) throw new Error(res.error || "AI 解读返回为空");
        setNarrative(res.narrative);
      } catch (e: any) {
        setAiError(e?.message ?? String(e));
      } finally {
        setAiLoading(false);
      }
    },
    [date]
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
          {[0, 1, 2, 3, 4].map((s) => (
            <button
              key={s}
              onClick={() => setStage(s)}
              className={cn(
                "px-2.5 py-1 text-sm border rounded-md transition-colors",
                stage === s ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted"
              )}
            >
              {s === 0 ? "自动" : STAGE_NAMES[s]}
            </button>
          ))}
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

          {/* AI 叙事 */}
          <div className="rounded-lg bg-card border p-4 space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h3 className="font-semibold text-sm flex items-center gap-1.5">
                <Sparkles className="h-4 w-4 text-violet-500" /> AI 复盘解读
              </h3>
              <div className="flex gap-2">
                {!narrative && (
                  <button
                    onClick={() => runNarrative(false)}
                    disabled={aiLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    {aiLoading ? "生成中（约1分钟）…" : "生成解读"}
                  </button>
                )}
                {narrative && (
                  <button
                    onClick={() => runNarrative(true)}
                    disabled={aiLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5", aiLoading && "animate-spin")} /> 重新生成
                  </button>
                )}
              </div>
            </div>
            {aiError && <p className="text-xs text-destructive">生成失败: {aiError}</p>}
            {narrative ? (
              <div className="text-sm leading-relaxed whitespace-pre-wrap">{narrative}</div>
            ) : !aiLoading ? (
              <p className="text-xs text-muted-foreground">基于四阶段结构化结果，由 LLM 生成自然语言复盘（规则判定不变）</p>
            ) : null}
          </div>

          <p className="text-xs text-muted-foreground text-center">
            方法论来源：淘股吧「可爱苏酥」· 核心逻辑：竞价无聚焦 = 资金无共识 = 当天难做 · 以上为方法论参考，不构成投资建议
          </p>
        </>
      ) : (
        <div className="border rounded-lg p-12 text-center text-muted-foreground text-sm">无数据</div>
      )}
    </div>
  );
}

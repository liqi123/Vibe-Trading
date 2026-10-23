import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Activity, Loader2, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { IntradayChart, type IntradayMarker } from "@/components/charts/IntradayChart";

interface Rule {
  key: string;
  name: string;
  state: "pass" | "weak" | "fail" | "na";
  detail: string;
}

interface Transition {
  idx: number;
  time: string;
  verdict: "可以买" | "观察" | "不买";
  price: number;
  reason: string;
}

interface Replay {
  steps: number;
  transitions: Transition[];
  first_buy: { idx: number; time: string; price: number } | null;
  after_signal: {
    end_time: string | null;
    end_chg_pct: number | null;
    max_gain_pct: number | null;
    max_drawdown_pct: number | null;
  } | null;
}

interface JudgeResult {
  code: string;
  name?: string;
  date?: string;
  time?: string;
  price?: number;
  change_pct?: number | null;
  vwap?: number;
  wave1_top?: number;
  pb_low?: number | null;
  bar_count?: number;
  verdict: "可以买" | "观察" | "不买";
  reason: string;
  rules: Rule[];
  detail?: string;
  replay?: Replay | null;
}

interface IntradayPayload {
  bars: { t: string; p: number; v: number }[];
  prev_close: number | null;
}

const VERDICT_CLS: Record<string, string> = {
  可以买: "bg-red-500/10 text-red-600 border-red-500/30",
  观察: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  不买: "bg-green-500/10 text-green-600 border-green-500/30",
};

const STATE_CLS: Record<Rule["state"], string> = {
  pass: "text-green-600",
  weak: "text-amber-600",
  fail: "text-red-600",
  na: "text-muted-foreground/60",
};

function StateIcon({ state }: { state: Rule["state"] }) {
  if (state === "pass") return <span className={STATE_CLS.pass}>✓</span>;
  if (state === "weak") return <span className={STATE_CLS.weak}>⚠</span>;
  if (state === "fail") return <span className={STATE_CLS.fail}>✗</span>;
  return <span className={STATE_CLS.na}>○</span>;
}

export function IntradayAnalysis() {
  const [params, setParams] = useSearchParams();
  const [codeInput, setCodeInput] = useState(params.get("code") ?? "");
  const [judge, setJudge] = useState<JudgeResult | null>(null);
  const [chart, setChart] = useState<IntradayPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (raw: string) => {
    const code = raw.trim();
    if (!code) return;
    setLoading(true);
    setError(null);
    setParams({ code });
    try {
      const [j, c] = await Promise.all([
        api.tools.get<JudgeResult>(`/stock/${code}/intraday-judge`),
        api.tools.get<IntradayPayload>(`/stock/${code}/intraday`).catch(() => null),
      ]);
      setJudge(j);
      setChart(c && c.bars?.length ? c : null);
      if (j.detail) setError(j.detail);
    } catch (e: unknown) {
      setJudge(null);
      setChart(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [setParams]);

  const chg = judge?.change_pct;
  const chgCls = chg == null ? "" : chg >= 0 ? "text-red-500" : "text-green-500";
  const replay = judge?.replay ?? null;

  const markers = useMemo<IntradayMarker[]>(() => {
    if (!replay || !chart) return [];
    const byTime = new Map(chart.bars.map((b) => [b.t, b.p]));
    return replay.transitions
      .filter((t) => t.verdict === "可以买")
      .map((t) => ({
        t: t.time,
        p: byTime.get(t.time) ?? t.price,
        color: "#ef4444",
        label: `可以买 ${t.time} @${t.price.toFixed(2)}`,
      }));
  }, [replay, chart]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Activity className="h-5 w-5" /> 分时买点判定
        </h1>
        {judge && (
          <button
            onClick={() => load(judge.code)}
            disabled={loading}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
        )}
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          load(codeInput);
        }}
      >
        <input
          value={codeInput}
          onChange={(e) => setCodeInput(e.target.value)}
          placeholder="股票代码或名称，如 300369 / 绿盟科技"
          className="px-3 py-2 text-sm border rounded-md bg-background w-64"
        />
        <button
          type="submit"
          disabled={loading || !codeInput.trim()}
          className="flex items-center gap-1.5 px-4 py-2 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          判定
        </button>
        <span className="text-xs text-muted-foreground">
          五规则：站上分时均价线 · 回踩不破线 · 回踩缩量 · 底部稳定 · 二波上攻
        </span>
      </form>

      {error && (
        <div className="border rounded-lg p-4 text-sm text-destructive">加载失败: {error}</div>
      )}

      {loading && !judge && (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" />
        </div>
      )}

      {judge && !loading && (
        <div className="space-y-4">
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-lg font-semibold">{judge.name || judge.code}</span>
              <span className="font-mono text-xs text-muted-foreground">{judge.code}</span>
              {judge.price != null && (
                <span className={cn("font-mono text-lg font-bold", chgCls)}>
                  {judge.price.toFixed(2)}
                </span>
              )}
              {chg != null && (
                <span className={cn("font-mono text-sm", chgCls)}>
                  {chg >= 0 ? "+" : ""}{chg.toFixed(2)}%
                </span>
              )}
              <span className="ml-auto text-xs text-muted-foreground font-mono">
                {judge.date} {judge.time} · {judge.bar_count} 根
                {judge.vwap != null && ` · 分时均价 ${judge.vwap.toFixed(2)}`}
                {judge.wave1_top != null && ` · 前高 ${judge.wave1_top.toFixed(2)}`}
              </span>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={cn(
                  "inline-flex items-center px-3 py-1.5 rounded-md border text-base font-bold",
                  VERDICT_CLS[judge.verdict] ?? "bg-muted text-muted-foreground border-border",
                )}
              >
                {judge.verdict}
              </span>
              <span className="text-sm text-muted-foreground">{judge.reason}</span>
              <span className="text-xs text-muted-foreground/70">
                （收盘终态，基于全天结构；择时请看下方时间序复盘）
              </span>
            </div>
          </div>

          {judge.rules.length > 0 && (
            <div className="rounded-lg border bg-card divide-y divide-border/30">
              {judge.rules.map((r) => (
                <div key={r.key} className="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <span className="font-mono text-xs text-muted-foreground mt-0.5 w-6">
                    {r.key.toUpperCase()}
                  </span>
                  <span className={cn("w-28 shrink-0 font-medium", STATE_CLS[r.state])}>
                    <StateIcon state={r.state} /> {r.name}
                  </span>
                  <span className="text-muted-foreground">{r.detail}</span>
                </div>
              ))}
            </div>
          )}

          {replay && replay.transitions.length > 0 && (
            <div className="rounded-lg border bg-card p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold">按时间复盘全天信号</p>
                <span className="text-xs text-muted-foreground">
                  逐根判定，每步只用该时点之前的分时（不含未来K）· 共 {replay.steps} 步
                </span>
              </div>

              <div className="rounded-md bg-muted/40 p-3 text-sm">
                {replay.first_buy ? (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-medium">首次「可以买」</span>
                    <span className="font-mono font-semibold text-red-600">
                      {replay.first_buy.time} @{replay.first_buy.price.toFixed(2)}
                    </span>
                    {replay.after_signal && replay.after_signal.end_chg_pct != null && (
                      <span className="text-muted-foreground">
                        → 之后到 {replay.after_signal.end_time}：
                        <span className={cn("font-mono", replay.after_signal.end_chg_pct >= 0 ? "text-red-600" : "text-green-600")}>
                          {replay.after_signal.end_chg_pct >= 0 ? "+" : ""}{replay.after_signal.end_chg_pct}%
                        </span>
                        （区间最高 <span className="font-mono text-red-600">+{replay.after_signal.max_gain_pct}%</span>
                        / 最低 <span className="font-mono text-green-600">{replay.after_signal.max_drawdown_pct}%</span>）
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="text-muted-foreground">全天未出现「可以买」信号</span>
                )}
              </div>

              <div className="divide-y divide-border/30">
                {replay.transitions.map((t) => (
                  <div key={t.idx} className="flex items-start gap-3 py-1.5 text-sm">
                    <span className="font-mono text-xs text-muted-foreground w-10 shrink-0 mt-0.5">
                      {t.time}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center px-1.5 py-0.5 rounded border text-xs font-medium w-14 justify-center shrink-0",
                        VERDICT_CLS[t.verdict] ?? "bg-muted text-muted-foreground border-border",
                      )}
                    >
                      {t.verdict}
                    </span>
                    <span className="font-mono text-xs w-14 shrink-0 mt-0.5 text-right">
                      {t.price.toFixed(2)}
                    </span>
                    <span className="text-xs text-muted-foreground">{t.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {chart && (
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground mb-2">
                当日分时（1分钟）· 红色标记 = 复盘中首次出现「可以买」的时点
              </p>
              <IntradayChart
                bars={chart.bars}
                prevClose={chart.prev_close}
                height={300}
                markers={markers}
              />
            </div>
          )}
        </div>
      )}

      {!judge && !loading && !error && (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <p className="text-sm">输入股票代码或名称，按分时五规则判定现在可不可以买</p>
          <p className="mt-1 text-xs">
            规则：① 现价站上分时均价线 ② 回踩不破线（破后收回=弱） ③ 回踩缩量 ④ 低点后5根未新低且距低点≥1% ⑤ 逼近/突破日内前高
          </p>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        ⚠ 数据来自腾讯实时行情 + 当日1分钟K线；开盘前10分钟、非交易时段（沿用最近交易日分时）仅供参考。
        「按时间复盘」逐根判定，每步只用该时点之前的分时、不含未来K（无马后炮）；顶部大字为收盘终态、仅基于全天结构、不作为择时依据。
        「可以买」仅指分时结构满足回踩买点条件，不构成投资建议，请结合日线与仓位纪律。
      </p>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { Gauge, RefreshCw, Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Row {
  date: string;
  afgi: number;
  state: string;
  ma5: number;
  ma20: number;
  change: number;
  hs300_close?: number | null;
  sh_close?: number | null;
  zz1000_close?: number | null;
  cyb_close?: number | null;
  [key: string]: number | string | null | undefined;
}
interface Component { key: string; label: string }
interface IndexMeta { key: string; label: string }
interface SeriesPayload {
  latest?: Row;
  components?: Component[];
  indexes?: IndexMeta[];
  rows?: Row[];
  explanation?: string;
  indicators?: IndicatorRow[];
  error?: string;
}
interface IndicatorRow { name: string; value: number | null; score: number; direction: string }

const stateColor = (s: string) => {
  switch (s) {
    case "极度恐惧": return "text-success";
    case "恐惧": return "text-success";
    case "中性": return "text-muted-foreground";
    case "贪婪": return "text-danger";
    case "极度贪婪": return "text-danger";
    default: return "text-muted-foreground";
  }
};

const fmt = (v: number | null | undefined, digits = 1) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(digits));

function SparkLine({ rows, overlayKey, overlayLabel }: { rows: Row[]; overlayKey: string; overlayLabel: string }) {
  const w = 900, h = 240, pad = 30;
  if (!rows || rows.length < 2) return <p className="p-6 text-center text-sm text-muted-foreground">数据不足</p>;
  const vals = rows.map((r) => Number(r.afgi));
  const min = Math.min(...vals, 0), max = Math.max(...vals, 100);
  const x = (i: number) => pad + (i * (w - pad * 2)) / (rows.length - 1);
  const y = (v: number) => h - pad - ((v - min) * (h - pad * 2)) / (max - min);
  const path = rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(Number(r.afgi)).toFixed(1)}`).join(" ");
  const ma5 = rows.map((r) => y(Number(r.ma5))).filter((v) => !Number.isNaN(v));
  const ma5Path = ma5.length ? rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(Number(r.ma5)).toFixed(1)}`).join(" ") : "";
  const overlayVals = rows.map((r) => Number(r[`${overlayKey}_close`])).filter((v) => !Number.isNaN(v));
  const overlayMin = Math.min(...overlayVals), overlayMax = Math.max(...overlayVals);
  const overlaySpan = overlayMax - overlayMin || 1;
  const yOverlay = (v: number) => y(((v - overlayMin) / overlaySpan) * 100);
  const overlayPath = rows
    .map((r, i) => (Number.isNaN(Number(r[`${overlayKey}_close`])) ? "" : `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${yOverlay(Number(r[`${overlayKey}_close`])).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");
  const last = rows[rows.length - 1];
  const lastOverlay = Number(last[`${overlayKey}_close`]);
  const tickCount = Math.min(9, rows.length);
  const tickEvery = Math.max(1, Math.floor((rows.length - 1) / (tickCount - 1)));
  const ticks = rows.filter((_, i) => i % tickEvery === 0 || i === rows.length - 1);
  const zone = (lo: number, hi: number, cls: string) => (
    <rect key={cls} x={pad} y={y(hi)} width={w - pad * 2} height={Math.max(0, y(lo) - y(hi))} className={cls} />
  );
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
      {zone(80, 100, "fill-danger/5")}
      {zone(60, 80, "fill-danger/10")}
      {zone(40, 60, "fill-muted/10")}
      {zone(20, 40, "fill-success/10")}
      {zone(0, 20, "fill-success/5")}
      {[0, 20, 40, 60, 80, 100].map((v) => (
        <g key={v}>
          <line x1={pad} y1={y(v)} x2={w - pad} y2={y(v)} stroke="currentColor" strokeOpacity="0.08" strokeDasharray="4 4" />
          <text x={w - pad + 4} y={y(v) + 3} fontSize="10" className="fill-muted-foreground/60">{v}</text>
        </g>
      ))}
      <text x={w - pad + 4} y={y(100) + 10} fontSize="9" className="fill-muted-foreground/50">贪婪</text>
      <text x={w - pad + 4} y={y(0) + 10} fontSize="9" className="fill-muted-foreground/50">恐惧</text>
      {ticks.map((r) => (
        <text key={r.date} x={x(rows.indexOf(r))} y={h - 8} fontSize="9" textAnchor="middle" className="fill-muted-foreground/60">
          {r.date.slice(5)}
        </text>
      ))}
      {ma5Path && <path d={ma5Path} fill="none" strokeWidth="1.2" className="stroke-muted-foreground/50" strokeDasharray="3 3" />}
      <path d={path} fill="none" strokeWidth="2" className="stroke-primary" />
      {overlayPath && (
        <>
          <path d={overlayPath} fill="none" strokeWidth="1.5" className="stroke-success" />
          <circle cx={x(rows.length - 1)} cy={yOverlay(lastOverlay)} r="3.5" className="fill-success" />
          <text x={x(rows.length - 1) - 30} y={yOverlay(lastOverlay) - 8} fontSize="10" className="fill-success font-medium">
            {overlayLabel} {fmt(lastOverlay, 0)}
          </text>
        </>
      )}
      {rows.map((r, i) => (
        <circle key={r.date} cx={x(i)} cy={y(Number(r.afgi))} r="5" className="fill-transparent">
          <title>{`${r.date}  AFGI ${fmt(r.afgi)}${Number.isNaN(Number(r.ma5)) ? "" : `  MA5 ${fmt(r.ma5)}`}`}</title>
        </circle>
      ))}
      <circle cx={x(rows.length - 1)} cy={y(Number(last.afgi))} r="4" className="fill-primary" />
      <text x={x(rows.length - 1) - 30} y={y(Number(last.afgi)) - 10} fontSize="11" className="fill-primary font-medium">
        {last.date} {fmt(last.afgi)}
      </text>
    </svg>
  );
}

export function SentimentIndex() {
  const [payload, setPayload] = useState<SeriesPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState("1y");

  const load = useCallback(async (r: string) => {
    setLoading(true);
    setError(null);
    try {
      const days = { "3m": 90, "6m": 180, "1y": 365, "2y": 730 }[r] ?? 365;
      const end = new Date();
      const start = new Date(end.getTime() - days * 86400000);
      const s = `${start.getFullYear()}${String(start.getMonth() + 1).padStart(2, "0")}${String(start.getDate()).padStart(2, "0")}`;
      const e = `${end.getFullYear()}${String(end.getMonth() + 1).padStart(2, "0")}${String(end.getDate()).padStart(2, "0")}`;
      const res = await api.tools.get<SeriesPayload>(`/sentiment/series?start=${s}&end=${e}`);
      setPayload(res);
      if (res.error) setError(res.error);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(range); }, [range]);

  const rows = payload?.rows ?? [];
  const latest = payload?.latest;
  const components = payload?.components ?? [];
  const indexes = payload?.indexes ?? [];
  const [overlayKey, setOverlayKey] = useState("hs300");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const latestDate = payload?.latest?.date ?? "";

  const runAiAnalysis = useCallback(
    async (force = false) => {
      setAiLoading(true);
      setAiError(null);
      try {
        const res = await api.tools.post<{ ok: boolean; analysis?: string; error?: string }>(
          "/sentiment/ai-analysis",
          { date: latestDate, refresh: force }
        );
        if (!res.ok || !res.analysis) throw new Error(res.error || "AI 分析返回为空");
        setAiAnalysis(res.analysis);
      } catch (e: any) {
        setAiError(e?.message ?? String(e));
      } finally {
        setAiLoading(false);
      }
    },
    [latestDate]
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2"><Gauge className="h-5 w-5" /> A股恐惧贪婪指数（AFGI）</h1>
        <div className="ml-auto flex items-center gap-2">
          {(["3m", "6m", "1y", "2y"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={cn("px-2.5 py-1 text-sm border rounded-md transition-colors", range === r ? "bg-primary text-primary-foreground" : "bg-background hover:bg-muted")}
            >
              {r.toUpperCase()}
            </button>
          ))}
          <button onClick={() => load(range)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
        </div>
      </div>

      {loading ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground"><Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" /></div>
      ) : error ? (
        <div className="border rounded-lg p-12 text-center">
          <p className="text-sm text-destructive">加载失败: {error}</p>
          <p className="mt-2 text-xs text-muted-foreground">可稍后重试；行业数据不可用时分项自动降级为中性（50）</p>
        </div>
      ) : latest ? (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-lg bg-card border p-4">
              <p className="text-xs text-muted-foreground">最新 AFGI</p>
              <p className={cn("mt-1 text-3xl font-bold", stateColor(latest.state))}>{fmt(latest.afgi)}</p>
              <p className={cn("mt-0.5 text-xs font-medium", stateColor(latest.state))}>{latest.state}</p>
            </div>
            <div className="rounded-lg bg-card border p-4">
              <p className="text-xs text-muted-foreground">较前日</p>
              <p className={cn("mt-1 text-2xl font-bold", Number(latest.change) >= 0 ? "text-danger" : "text-success")}>
                {Number(latest.change) >= 0 ? "+" : ""}{fmt(latest.change)}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">{latest.date}</p>
            </div>
            <div className="rounded-lg bg-card border p-4">
              <p className="text-xs text-muted-foreground">MA5</p>
              <p className="mt-1 text-2xl font-bold text-primary">{fmt(latest.ma5)}</p>
            </div>
            <div className="rounded-lg bg-card border p-4">
              <p className="text-xs text-muted-foreground">MA20</p>
              <p className="mt-1 text-2xl font-bold text-primary">{fmt(latest.ma20)}</p>
            </div>
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-muted-foreground">AFGI 曲线（{">"}80 贪婪 / {"<"}20 恐惧 / MA5 虚线）</h3>
              <div className="ml-auto flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">叠加:</span>
                {indexes.map((ix) => (
                  <button
                    key={ix.key}
                    onClick={() => setOverlayKey(ix.key)}
                    className={cn(
                      "px-2 py-0.5 text-xs border rounded-md transition-colors",
                      overlayKey === ix.key ? "bg-success/15 border-success/40 text-success" : "bg-background hover:bg-muted",
                    )}
                  >
                    {ix.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="border rounded-lg p-3 bg-card">
              <SparkLine rows={rows} overlayKey={overlayKey} overlayLabel={indexes.find((i) => i.key === overlayKey)?.label ?? ""} />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="text-primary font-medium">蓝线</span> AFGI（0-100），
              <span className="text-success font-medium">绿线</span> 叠加指数（区间归一化，仅看形态对比：情绪与大盘同步/背离）
            </p>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold text-muted-foreground">分项分解（最新）</h3>
            <div className="border rounded-lg p-4 bg-card">
              <div className="grid gap-3 sm:grid-cols-3">
                {components.map((c) => {
                  const v = Number(latest[c.key] ?? 50);
                  return (
                    <div key={c.key} className="rounded-lg bg-muted/20 p-3">
                      <div className="flex items-baseline justify-between">
                        <p className="text-xs text-muted-foreground">{c.label}</p>
                        <p className="font-mono text-lg font-bold">{v.toFixed(1)}</p>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full bg-muted/40 overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", v >= 60 ? "bg-danger" : v <= 40 ? "bg-success" : "bg-muted-foreground/50")}
                          style={{ width: `${v}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {payload?.explanation && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold text-muted-foreground">情绪解读（规则）</h3>
                <button
                  onClick={() => runAiAnalysis(!!aiAnalysis)}
                  disabled={aiLoading}
                  className="ml-auto flex items-center gap-1.5 px-3 py-1 text-xs border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                >
                  {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {aiLoading ? "AI 分析中..." : aiAnalysis ? "重新生成" : "AI 深度分析"}
                </button>
              </div>
              <div className="border rounded-lg p-4 bg-card text-sm leading-relaxed whitespace-pre-line">{payload.explanation}</div>
              {aiError && <p className="mt-2 text-xs text-destructive">AI 分析失败: {aiError}</p>}
              {aiAnalysis && (
                <div className="mt-2 border rounded-lg p-4 bg-muted/20 text-sm leading-relaxed whitespace-pre-line">{aiAnalysis}</div>
              )}
            </div>
          )}

          {payload?.indicators?.length ? (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-muted-foreground">原始指标一览（最新）</h3>
              <div className="border rounded-lg p-4 bg-card">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                        {["指标", "方向", "原始值", "得分"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {payload.indicators.map((it) => (
                        <tr key={it.name} className="border-b border-border/30">
                          <td className="px-2 py-2 font-medium">{it.name}</td>
                          <td className={cn("px-2 py-2 text-xs", it.direction === "正向" ? "text-danger" : "text-success")}>{it.direction}</td>
                          <td className="px-2 py-2 font-mono">{it.value == null ? "—" : it.value}</td>
                          <td className="px-2 py-2 font-mono">{it.score.toFixed(1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <div className="border rounded-lg p-12 text-center text-muted-foreground"><p className="text-sm">暂无数据</p></div>
      )}
    </div>
  );
}

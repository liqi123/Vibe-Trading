import { useCallback, useEffect, useState } from "react";
import { Eye, RefreshCw, Loader2, AlertTriangle, Radio } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Signal {
  code: string;
  name: string;
  action: string;
  size: string;
  snippet: string;
  source: string;
  ts: string;
  conflict: boolean;
}
interface Payload {
  date?: string;
  dates?: string[];
  follows?: { count: number; names: string[] };
  users?: { user: string; signals: Signal[] }[];
  total?: number;
  conflicts?: number;
  error?: string;
}

const ACTION_CN: Record<string, string> = { SELL: "卖出", BUY: "买入", PLAN: "计划", HOLD: "持有" };
const SIZE_CN: Record<string, string> = { LIGHT: "轻仓", HALF: "半仓", HEAVY: "重仓" };

const actionCls = (a: string) =>
  a === "BUY"
    ? "bg-danger/10 text-danger border-danger/30"
    : a === "SELL"
      ? "bg-success/10 text-success border-success/30"
      : a === "PLAN"
        ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
        : "bg-muted/40 text-muted-foreground border-border";

export function TgbSignals() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [pollLog, setPollLog] = useState<string | null>(null);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.tools.get<Payload>(`/tgb/signals?date=${d}`);
      setPayload(res);
      if (res.error) setError(res.error);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(date); }, [date]);

  const poll = useCallback(async () => {
    setPolling(true);
    setPollLog(null);
    try {
      const res = await api.tools.post<{ ok: boolean; log?: string; error?: string }>("/tgb/refresh");
      if (!res.ok) throw new Error(res.error || "轮询失败");
      setPollLog(res.log || "（无输出）");
      await load(date);
    } catch (e: any) {
      setPollLog(`轮询失败：${e?.message ?? String(e)}`);
    } finally {
      setPolling(false);
    }
  }, [date]);

  const users = payload?.users ?? [];
  const names = payload?.follows?.names ?? [];

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2"><Eye className="h-5 w-5" /> 淘股吧关注信号监控</h1>
        <div className="ml-auto flex items-center gap-2">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-2.5 py-1 text-sm border rounded-md bg-background"
          />
          <button onClick={() => load(date)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
          <button onClick={poll} disabled={polling} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50">
            {polling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radio className="h-3.5 w-3.5" />}
            {polling ? "轮询中..." : "立即轮询"}
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">关注用户</p>
          <p className="mt-1 text-3xl font-bold">{payload?.follows?.count ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground truncate" title={names.join("、")}>{names.slice(0, 6).join("、")}{names.length > 6 ? ` 等${names.length}人` : ""}</p>
        </div>
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">当日信号</p>
          <p className="mt-1 text-3xl font-bold text-primary">{payload?.total ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{payload?.users?.length ?? 0} 人有可执行动作</p>
        </div>
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">口径冲突</p>
          <p className={cn("mt-1 text-3xl font-bold", (payload?.conflicts ?? 0) > 0 ? "text-amber-600" : "")}>{payload?.conflicts ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">与空仓声明冲突的买卖动作</p>
        </div>
      </div>

      {loading ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground"><Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" /></div>
      ) : error ? (
        <div className="border rounded-lg p-12 text-center"><p className="text-sm text-destructive">加载失败: {error}</p></div>
      ) : users.length === 0 ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <p className="text-sm">{date} 无归档信号</p>
          <p className="mt-1 text-xs">点击「立即轮询」抓取最新动态（需在根项目 .env 配置 TGB_USER/TGB_PWD）</p>
        </div>
      ) : (
        <div className="space-y-4">
          {users.map((g) => (
            <div key={g.user}>
              <h3 className="mb-2 text-sm font-semibold text-muted-foreground flex items-center gap-2">
                {g.user}
                <span className="text-xs font-normal">({g.signals.length})</span>
              </h3>
              <div className="border rounded-lg bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["动作", "股票", "仓位", "上下文", "来源", "时间"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {g.signals.map((s, i) => (
                      <tr key={`${s.code}-${s.ts}-${i}`} className="border-b border-border/30 last:border-0">
                        <td className="px-3 py-2">
                          <span className={cn("inline-block px-1.5 py-0.5 text-xs border rounded", actionCls(s.action))}>
                            {ACTION_CN[s.action] ?? s.action}
                          </span>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap font-medium">
                          {s.name}
                          <span className="ml-1.5 text-xs text-muted-foreground font-mono">{s.code}</span>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{SIZE_CN[s.size] ?? "—"}</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground max-w-md truncate" title={s.snippet}>
                          {s.conflict && <AlertTriangle className="inline h-3.5 w-3.5 mr-1 text-amber-600" />}
                          {s.snippet}
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{s.source}</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap font-mono">{(s.ts ?? "").slice(11, 16)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {pollLog && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">轮询日志</h3>
          <pre className="border rounded-lg p-4 bg-muted/20 text-xs leading-relaxed overflow-x-auto whitespace-pre-wrap">{pollLog}</pre>
        </div>
      )}

      <p className="text-xs text-muted-foreground">⚠ 提取信号≠实盘持仓，仅供参考，决策前请核对原文。自动轮询时段 9:15-15:00（手动轮询不受限）。</p>
    </div>
  );
}

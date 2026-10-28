import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, ClipboardList, Loader2, RefreshCw, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PlanItem {
  index: number;
  text: string;
  achieved: boolean | null;
  reason: string;
  group?: string;
}
interface PlanList {
  ok: boolean;
  error?: string;
  exists: boolean;
  items: PlanItem[];
  checked_at?: string | null;
  plan_full?: string | null;
}

/**
 * 交易计划卡：导入 txt（每行一条）→ 竞价数据采集后由项目 LLM 逐条核对，达成打勾。
 * checkKey 变化（+1）时自动重跑核对，由父组件在「采集竞价」成功后触发。
 */
export function TradePlanCard({
  date,
  auctionExists,
  checkKey,
}: {
  date: string;
  auctionExists: boolean;
  checkKey: number;
}) {
  const [data, setData] = useState<PlanList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [checking, setChecking] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const lastCheckKey = useRef(0);

  const load = useCallback(async () => {
    try {
      const res = await api.tools.get<PlanList>(`/trade-plan/list?date=${date}`);
      setData(res);
      setError(res.ok ? null : res.error ?? "读取失败");
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  }, [date]);

  useEffect(() => {
    lastCheckKey.current = 0;
    setData(null);
    load();
  }, [load]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      const res = await api.tools.post<PlanList>("/trade-plan/check", { date });
      if (res.ok) {
        setError(null);
        setData(res);
      } else {
        setError(res.error ?? "核对失败");
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setChecking(false);
    }
  }, [date]);

  // 采集竞价成功后自动核对（父组件递增 checkKey 触发一次）
  useEffect(() => {
    if (checkKey === lastCheckKey.current) return;
    lastCheckKey.current = checkKey;
    if (checkKey > 0 && (data?.items.length ?? 0) > 0) void runCheck();
  }, [checkKey, data, runCheck]);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setImporting(true);
    try {
      const text = await f.text();
      const res = await api.tools.post<{ ok: boolean; error?: string }>("/trade-plan/import", { date, text });
      if (res.ok) {
        setError(null);
        await load();
      } else {
        setError(res.error ?? "导入失败");
      }
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  };

  const items = data?.items ?? [];
  const achievedCount = items.filter((i) => i.achieved).length;

  // 按分节分组展示（group 为空归到「计划」）
  const groups: { title: string; items: PlanItem[] }[] = [];
  const groupIndex = new Map<string, number>();
  for (const it of items) {
    const g = it.group || "计划";
    let gi = groupIndex.get(g);
    if (gi === undefined) {
      gi = groups.length;
      groupIndex.set(g, gi);
      groups.push({ title: g, items: [] });
    }
    groups[gi].items.push(it);
  }

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ClipboardList className="h-5 w-5 text-amber-500" />
        <h2 className="font-semibold text-base">交易计划</h2>
        <span className="text-xs text-muted-foreground">盘前写好 txt · 竞价后自动核对</span>
        <div className="ml-auto flex flex-wrap gap-2">
          <input ref={fileRef} type="file" accept=".txt,text/plain" className="hidden" onChange={onFile} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            导入 txt
          </button>
          {items.length > 0 && (
            <button
              onClick={() => runCheck()}
              disabled={checking || !auctionExists}
              title={auctionExists ? "重新核对" : "先采集竞价数据"}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
            >
              {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              核对计划
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {data?.exists && items.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="px-2 py-0.5 rounded-full bg-green-500/15 text-green-600 border border-green-500/30">
              {achievedCount}/{items.length} 达成
            </span>
            {data.checked_at ? (
              <span>核对于 {data.checked_at}</span>
            ) : (
              <span>尚未核对{auctionExists ? "：点「核对计划」" : "：采集竞价后自动核对"}</span>
            )}
            {checking && (
              <span className="flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> LLM 核对中…
              </span>
            )}
          </div>

          {groups.map((g) => (
            <div key={g.title} className="space-y-1.5">
              {g.title && (
                <h3 className="text-xs font-medium text-foreground/80 mt-1">{g.title}</h3>
              )}
              <ul className="space-y-1.5">
                {g.items.map((it) => (
                  <li key={it.index} className="flex items-start gap-2 rounded-md border p-2">
                    {it.achieved === null ? (
                      <Circle className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground/50" />
                    ) : it.achieved ? (
                      <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0 text-green-500" />
                    ) : (
                      <Circle className="h-4 w-4 mt-0.5 shrink-0 text-amber-500" />
                    )}
                    <div className="min-w-0">
                      <p className={cn("text-sm leading-snug", it.achieved === false && "text-muted-foreground")}>{it.text}</p>
                      {it.reason && <p className="mt-0.5 text-xs text-muted-foreground">{it.reason}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {data.plan_full && (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer select-none hover:text-foreground/80">查看计划全文（含锚点/持仓/纪律）</summary>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/50 p-2 leading-relaxed">{data.plan_full}</pre>
            </details>
          )}
        </>
      ) : (
        !error && (
          <p className="text-xs text-muted-foreground">
            尚未导入交易计划：点右上「导入 txt」。支持编号条目（1. 2. 3.）作为核对项，分节标题（一、二、）与表格作为上下文；# 开头为注释行。
          </p>
        )
      )}
    </div>
  );
}

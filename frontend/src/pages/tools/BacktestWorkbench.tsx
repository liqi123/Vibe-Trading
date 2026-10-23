import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, Loader2, Play, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface BtMetrics {
  total_return?: number;
  annual_return?: number;
  max_drawdown?: number;
  sharpe?: number;
  win_rate?: number;
  profit_factor?: number;
  trade_count?: number;
  excess_return?: number;
}

interface BtItem {
  name: string;
  run_dir: string;
  idea: string;
  codes_n: number;
  start_date: string;
  end_date: string;
  source: string;
  status: string;
  metrics: BtMetrics | null;
  generated_at: string;
}

interface TaskStatus {
  content: string;
  result?: { name: string; run_dir: string; codes_n: number };
}

const fmtPct = (x?: number | null): string =>
  x == null ? "—" : `${(x * 100).toFixed(2)}%`;
const fmtNum = (x?: number | null, d = 2): string =>
  x == null ? "—" : x.toFixed(d);

export function BacktestWorkbench() {
  const [items, setItems] = useState<BtItem[]>([]);
  const [idea, setIdea] = useState("");
  const [genOut, setGenOut] = useState("");
  const [runOut, setRunOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.tools.get<{ items: BtItem[] }>("/vibe/stats/backtests");
      setItems(res.items || []);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [load]);

  const pollTask = useCallback(
    (taskId: string, setOut: (s: string) => void, onDone?: (st: TaskStatus) => void) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const st = await api.tools.get<TaskStatus>(`/vibe/stats/backtests/status/${taskId}`);
          setOut(st.content || "");
          if ((st.content || "").includes("执行完成")) {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setBusy(false);
            if (st.content.includes("exit=0")) onDone?.(st);
          }
        } catch {
          /* keep polling */
        }
      }, 1500);
    },
    [],
  );

  const startRun = useCallback(
    async (runDir: string) => {
      setBusy(true);
      setErr("");
      setRunOut("");
      try {
        const { task_id } = await api.tools.post<{ task_id: string }>("/vibe/stats/backtests/run", {
          run_dir: runDir,
        });
        pollTask(task_id, setRunOut, () => load());
      } catch (e) {
        setBusy(false);
        setErr(String(e));
      }
    },
    [load, pollTask],
  );

  const gen = useCallback(async () => {
    if (!idea.trim()) return;
    setBusy(true);
    setErr("");
    setGenOut("");
    setRunOut("");
    try {
      const { task_id } = await api.tools.post<{ task_id: string }>("/vibe/stats/backtests/gen", {
        idea: idea.trim(),
      });
      pollTask(task_id, setGenOut, (st) => {
        if (st.result?.run_dir) startRun(st.result.run_dir);
      });
    } catch (e) {
      setBusy(false);
      setErr(String(e));
    }
  }, [idea, pollTask, startRun]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Brain className="h-6 w-6 text-purple-500" />
          对话回测
        </h1>
        <button
          onClick={load}
          className="flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>

      <div className="space-y-2 rounded-lg border p-4">
        <div className="text-sm font-medium">描述你的回测想法（LLM 生成规则 + 自动运行）</div>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          placeholder="例：20 日均线上方且放量突破的动量策略，回踩 MA10 加仓，跌破 MA20 清仓"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <div className="flex items-center gap-3">
          <button
            onClick={gen}
            disabled={busy || !idea.trim()}
            className="flex items-center gap-1.5 rounded-md bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            生成并运行
          </button>
          {err && <span className="text-sm text-red-500">{err}</span>}
        </div>
        {genOut && (
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-black/5 p-3 text-xs">
            {genOut}
          </pre>
        )}
        {runOut && (
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-black/5 p-3 text-xs">
            {runOut}
          </pre>
        )}
      </div>

      <div className="rounded-lg border">
        <div className="border-b px-4 py-2 text-sm font-medium">回测列表（agent/runs）</div>
        {items.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            还没有回测 run，先在上方描述一个想法
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2">想法</th>
                  <th className="px-3 py-2">区间</th>
                  <th className="px-3 py-2 text-right">标的</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2 text-right">总收益</th>
                  <th className="px-3 py-2 text-right">Sharpe</th>
                  <th className="px-3 py-2 text-right">回撤</th>
                  <th className="px-3 py-2 text-right">胜率</th>
                  <th className="px-3 py-2 text-right">交易</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.name} className="border-b last:border-0 hover:bg-accent/40">
                    <td className="px-3 py-2 font-mono text-xs">{it.name}</td>
                    <td className="max-w-[180px] truncate px-3 py-2" title={it.idea}>
                      {it.idea || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {it.start_date} ~ {it.end_date}
                    </td>
                    <td className="px-3 py-2 text-right">{it.codes_n}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-xs",
                          it.status === "done"
                            ? "bg-green-500/10 text-green-600"
                            : "bg-amber-500/10 text-amber-600",
                        )}
                      >
                        {it.status === "done" ? "已完成" : "待运行"}
                      </span>
                    </td>
                    <td
                      className={cn(
                        "px-3 py-2 text-right",
                        (it.metrics?.total_return ?? 0) >= 0 ? "text-red-500" : "text-green-500",
                      )}
                    >
                      {fmtPct(it.metrics?.total_return)}
                    </td>
                    <td className="px-3 py-2 text-right">{fmtNum(it.metrics?.sharpe)}</td>
                    <td className="px-3 py-2 text-right">{fmtPct(it.metrics?.max_drawdown)}</td>
                    <td className="px-3 py-2 text-right">{fmtPct(it.metrics?.win_rate)}</td>
                    <td className="px-3 py-2 text-right">{it.metrics?.trade_count ?? "—"}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => startRun(it.run_dir)}
                        disabled={busy}
                        className="rounded border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
                      >
                        运行
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

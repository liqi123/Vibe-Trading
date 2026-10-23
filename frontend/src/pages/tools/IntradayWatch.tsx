import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Layers, Loader2, Radar, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PriceRow {
  name: string;
  price: number;
  change_pct: number;
  prev_close: number;
  open: number;
  high: number;
  low: number;
}

interface PoolPos {
  code: string;
  name: string;
  category: string;
  price?: number;
  cost_price?: number;
  pnl_pct?: number;
}

interface PoolPayload {
  available: boolean;
  positions?: PoolPos[];
}

interface LadderStock {
  code: string;
  name: string;
  sector: string;
  boards: number;
  pct: number | null;
  status: "promoted" | "broken" | "pending";
}

interface LadderPayload {
  available: boolean;
  error?: string;
  reason?: string;
  date?: string;
  prev_date?: string;
  as_of?: string;
  summary?: {
    n_prev: number;
    promoted: number;
    broken: number;
    promotion_rate: number | null;
    median_pct: number | null;
    coverage: number;
  };
  ladder?: { boards: number; count: number; stocks: LadderStock[] }[];
}

interface MoverEvent {
  code: string;
  name: string;
  kind: "rapid_up" | "rapid_down" | "seal" | "broken";
  time: string;
  pct: number;
  price: number;
  limit_price?: number;
}

interface MoversPayload {
  available: boolean;
  as_of?: string;
  n_codes?: number;
  movers?: MoverEvent[];
  reason?: string;
}

const STATUS_LABEL: Record<LadderStock["status"], string> = {
  promoted: "晋级",
  broken: "炸板",
  pending: "未板",
};
const STATUS_CLS: Record<LadderStock["status"], string> = {
  promoted: "bg-red-500/10 text-red-500",
  broken: "bg-amber-500/10 text-amber-600",
  pending: "bg-muted text-muted-foreground",
};
const KIND_LABEL: Record<MoverEvent["kind"], string> = {
  rapid_up: "急拉",
  rapid_down: "急跌",
  seal: "封板",
  broken: "开板",
};
const KIND_CLS: Record<MoverEvent["kind"], string> = {
  rapid_up: "text-red-500",
  rapid_down: "text-green-500",
  seal: "text-red-500",
  broken: "text-amber-600",
};

const pctCls = (p?: number | null): string =>
  p == null ? "" : p > 0 ? "text-red-500" : p < 0 ? "text-green-500" : "";

export function IntradayWatch() {
  const [watchCodes, setWatchCodes] = useState<string[]>([]);
  const [prices, setPrices] = useState<Record<string, PriceRow>>({});
  const [poolPos, setPoolPos] = useState<PoolPos[]>([]);
  const [ladder, setLadder] = useState<LadderPayload | null>(null);
  const [movers, setMovers] = useState<MoversPayload | null>(null);
  const [now, setNow] = useState("");
  const [err, setErr] = useState("");
  const codesRef = useRef<string[]>([]);

  // 自选池代码（holding+observation），取一次
  useEffect(() => {
    api.tools
      .get<PoolPayload>("/vibe/stats/pool")
      .then((p) => {
        const pos = (p.positions || []).filter(
          (x) => x.category === "holding" || x.category === "observation",
        );
        setPoolPos(pos);
        const codes = pos.map((x) => x.code);
        codesRef.current = codes;
        setWatchCodes(codes);
      })
      .catch(() => setErr("自选池加载失败"));
  }, []);

  const loadPrices = useCallback(async () => {
    const codes = codesRef.current;
    if (!codes.length) return;
    try {
      const r = await api.tools.get<{ prices: Record<string, PriceRow> }>(
        `/prices?codes=${codes.join(",")}`,
      );
      setPrices(r.prices || {});
      setNow(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    } catch {
      /* keep stale */
    }
  }, []);

  const loadLadder = useCallback(async () => {
    try {
      const r = await api.tools.get<LadderPayload>("/vibe/stats/ladder-live");
      setLadder(r);
    } catch {
      /* keep stale */
    }
  }, []);

  const loadMovers = useCallback(async () => {
    try {
      const r = await api.tools.get<MoversPayload>("/vibe/stats/movers?threshold=1.5");
      setMovers(r);
    } catch {
      /* keep stale */
    }
  }, []);

  useEffect(() => {
    loadPrices();
    loadLadder();
    loadMovers();
    const p1 = setInterval(loadPrices, 3000);
    const p2 = setInterval(loadLadder, 30000);
    const p3 = setInterval(loadMovers, 60000);
    return () => {
      clearInterval(p1);
      clearInterval(p2);
      clearInterval(p3);
    };
  }, [loadPrices, loadLadder, loadMovers]);

  const refreshAll = () => {
    loadPrices();
    loadLadder();
    loadMovers();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Activity className="h-6 w-6 text-emerald-500" />
          盯盘实时
          <span className="text-sm font-normal text-muted-foreground">
            {now && `行情 ${now} · 3 秒刷新`} · 梯队 30 秒 · 异动 60 秒
          </span>
        </h1>
        <button
          onClick={refreshAll}
          className="flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>
      {err && <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-500">{err}</div>}

      {/* 自选持仓实时报价 */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Radar className="h-4 w-4" />
          自选持仓（{watchCodes.length} 只）
        </div>
        {watchCodes.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">自选池没有 holding/observation 标的，先去配置自选</div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {poolPos.map((pos) => {
              const q = prices[pos.code];
              return (
                <div key={pos.code} className="rounded-md border p-3">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm font-medium">{pos.name}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">{pos.code}</span>
                  </div>
                  {q ? (
                    <>
                      <div className={cn("mt-1 font-mono text-xl font-bold tabular-nums", pctCls(q.change_pct))}>
                        {q.price.toFixed(2)}
                      </div>
                      <div className={cn("font-mono text-xs", pctCls(q.change_pct))}>
                        {q.change_pct > 0 ? "+" : ""}
                        {q.change_pct.toFixed(2)}%
                        <span className="ml-1 text-muted-foreground">
                          开 {q.open.toFixed(2)} 高 {q.high.toFixed(2)} 低 {q.low.toFixed(2)}
                        </span>
                      </div>
                    </>
                  ) : (
                    <div className="mt-2 text-sm text-muted-foreground">
                      <Loader2 className="inline h-3 w-3 animate-spin" /> 拉取中…
                    </div>
                  )}
                  {pos.category === "holding" && pos.cost_price != null && (
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      成本 {pos.cost_price.toFixed(2)}
                      {pos.pnl_pct != null && (
                        <span className={cn("ml-1", pctCls(pos.pnl_pct))}>
                          {pos.pnl_pct > 0 ? "+" : ""}
                          {pos.pnl_pct.toFixed(2)}%
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 昨日涨停梯队·今日状态 */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Layers className="h-4 w-4" />
          昨日涨停梯队 · 今日状态
          {ladder?.as_of && (
            <span className="text-xs font-normal text-muted-foreground">
              {ladder.prev_date} 涨停 {ladder.summary?.n_prev} 只 · {ladder.as_of} 更新
            </span>
          )}
        </div>
        {!ladder ? (
          <div className="p-4 text-sm text-muted-foreground">
            <Loader2 className="inline h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : !ladder.available ? (
          <div className="p-4 text-sm text-muted-foreground">{ladder.reason || ladder.error || "暂不可用"}</div>
        ) : (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: "昨涨停", value: String(ladder.summary?.n_prev ?? "—") },
                {
                  label: "晋级",
                  value: `${ladder.summary?.promoted ?? 0}（${
                    ladder.summary?.promotion_rate != null
                      ? `${(ladder.summary.promotion_rate * 100).toFixed(0)}%`
                      : "—"
                  }）`,
                  cls: "text-red-500",
                },
                { label: "炸板", value: String(ladder.summary?.broken ?? 0), cls: "text-amber-600" },
                {
                  label: "池中位涨幅",
                  value:
                    ladder.summary?.median_pct != null
                      ? `${ladder.summary.median_pct > 0 ? "+" : ""}${ladder.summary.median_pct.toFixed(2)}%`
                      : "—",
                  cls: pctCls(ladder.summary?.median_pct),
                },
              ].map((t) => (
                <div key={t.label} className="rounded-md border p-2.5 text-center">
                  <div className={cn("font-mono text-lg font-bold tabular-nums", t.cls)}>{t.value}</div>
                  <div className="text-[11px] text-muted-foreground">{t.label}</div>
                </div>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="px-2 py-1.5">板位</th>
                    <th className="px-2 py-1.5">代码</th>
                    <th className="px-2 py-1.5">名称</th>
                    <th className="px-2 py-1.5">行业</th>
                    <th className="px-2 py-1.5 text-right">今日%</th>
                    <th className="px-2 py-1.5">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {(ladder.ladder || []).map((row) =>
                    row.stocks.map((s, i) => (
                      <tr key={`${s.code}-${i}`} className="border-b last:border-0 hover:bg-accent/40">
                        <td className="px-2 py-1.5 font-mono text-xs">{s.boards}板</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{s.code}</td>
                        <td className="px-2 py-1.5">{s.name}</td>
                        <td className="px-2 py-1.5 text-xs text-muted-foreground">{s.sector || "—"}</td>
                        <td className={cn("px-2 py-1.5 text-right font-mono", pctCls(s.pct))}>
                          {s.pct != null ? `${s.pct > 0 ? "+" : ""}${s.pct.toFixed(2)}%` : "—"}
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={cn("rounded px-1.5 py-0.5 text-xs", STATUS_CLS[s.status])}>
                            {STATUS_LABEL[s.status]}
                          </span>
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {/* 盯盘异动 */}
      <section className="rounded-lg border p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Radar className="h-4 w-4" />
          盯盘异动（3 分钟 ±1.5% · 封板开板）
          {movers?.as_of && (
            <span className="text-xs font-normal text-muted-foreground">
              盯 {movers.n_codes ?? 0} 只 · {movers.as_of} · 每 60 秒
            </span>
          )}
        </div>
        {!movers ? (
          <div className="p-4 text-sm text-muted-foreground">
            <Loader2 className="inline h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : !movers.available ? (
          <div className="p-4 text-sm text-muted-foreground">{movers.reason || "暂不可用"}</div>
        ) : (movers.movers || []).length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">暂无异动</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-2 py-1.5">时间</th>
                  <th className="px-2 py-1.5">代码</th>
                  <th className="px-2 py-1.5">名称</th>
                  <th className="px-2 py-1.5">类型</th>
                  <th className="px-2 py-1.5 text-right">变动</th>
                  <th className="px-2 py-1.5 text-right">现价</th>
                </tr>
              </thead>
              <tbody>
                {(movers.movers || []).map((m, i) => (
                  <tr key={`${m.code}-${m.kind}-${m.time}-${i}`} className="border-b last:border-0">
                    <td className="px-2 py-1.5 font-mono text-xs">{m.time}</td>
                    <td className="px-2 py-1.5 font-mono text-xs">{m.code}</td>
                    <td className="px-2 py-1.5">{m.name}</td>
                    <td className={cn("px-2 py-1.5", KIND_CLS[m.kind])}>{KIND_LABEL[m.kind]}</td>
                    <td className={cn("px-2 py-1.5 text-right font-mono", pctCls(m.pct))}>
                      {m.pct > 0 ? "+" : ""}
                      {m.pct.toFixed(2)}%
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono">{m.price.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Filter, Loader2, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface CandItem {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  pe_ttm: number;
  pb: number;
  mcap_yi: number;
  float_mcap_yi: number;
  turnover_pct: number;
  amount_wan: number;
  vol_ratio: number;
  category?: string;
}

interface CandPayload {
  available: boolean;
  error?: string;
  scope: string;
  as_of: string;
  universe: number;
  n: number;
  items: CandItem[];
  filters: Record<string, unknown>;
}

type Scope = "watchlist" | "holding" | "market";

const SCOPES: { key: Scope; label: string }[] = [
  { key: "watchlist", label: "自选" },
  { key: "holding", label: "持仓" },
  { key: "market", label: "全市场" },
];

const CAT_LABEL: Record<string, string> = { holding: "持仓", observation: "观察", candidate: "候选" };

const fmtWan = (w?: number): string =>
  w == null ? "—" : w >= 10000 ? `${(w / 10000).toFixed(1)}亿` : `${w.toFixed(0)}万`;

export function CandidatePool() {
  const [scope, setScope] = useState<Scope>("watchlist");
  const [payload, setPayload] = useState<CandPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [peMax, setPeMax] = useState("");
  const [pbMax, setPbMax] = useState("");
  const [mcapMin, setMcapMin] = useState("");
  const [mcapMax, setMcapMax] = useState("");
  const [turnMin, setTurnMin] = useState("");
  const [amtMin, setAmtMin] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    const p = new URLSearchParams({ scope, limit: "300" });
    if (q.trim()) p.set("q", q.trim());
    if (peMax) p.set("pe_max", peMax);
    if (pbMax) p.set("pb_max", pbMax);
    if (mcapMin) p.set("mcap_min", mcapMin);
    if (mcapMax) p.set("mcap_max", mcapMax);
    if (turnMin) p.set("turnover_min", turnMin);
    if (amtMin) p.set("amount_min", amtMin);
    try {
      const res = await api.tools.get<CandPayload>(`/vibe/stats/candidates?${p.toString()}`);
      if (!res.available) setErr(res.error || "不可用");
      setPayload(res);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, [scope, q, peMax, pbMax, mcapMin, mcapMax, turnMin, amtMin]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Filter className="h-6 w-6 text-blue-500" />
          候选池
          {payload && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {payload.as_of} · 全池 {payload.universe} · 命中 {payload.n}
              {payload.n > payload.items.length ? `（显示前 ${payload.items.length}）` : ""}
            </span>
          )}
        </h1>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          刷新
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border">
          {SCOPES.map((s) => (
            <button
              key={s.key}
              onClick={() => setScope(s.key)}
              className={cn(
                "px-3 py-1.5 text-sm",
                scope === s.key ? "bg-accent font-medium" : "hover:bg-accent/50",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="代码/名称"
            className="w-40 rounded-md border bg-background py-1.5 pl-8 pr-2 text-sm"
          />
        </div>
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={cn(
            "rounded-md border px-3 py-1.5 text-sm hover:bg-accent",
            showFilters && "bg-accent",
          )}
        >
          筛选{Object.keys(payload?.filters || {}).length > 0 ? ` (${Object.keys(payload!.filters).length})` : ""}
        </button>
      </div>

      {showFilters && (
        <div className="grid grid-cols-2 gap-3 rounded-lg border p-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
          {[
            { label: "PE ≤", value: peMax, set: setPeMax, ph: "亏损股自动排除" },
            { label: "PB ≤", value: pbMax, set: setPbMax, ph: "" },
            { label: "市值 ≥(亿)", value: mcapMin, set: setMcapMin, ph: "" },
            { label: "市值 ≤(亿)", value: mcapMax, set: setMcapMax, ph: "" },
            { label: "换手 ≥(%)", value: turnMin, set: setTurnMin, ph: "" },
            { label: "成交额 ≥(万)", value: amtMin, set: setAmtMin, ph: "" },
          ].map((f) => (
            <label key={f.label} className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">{f.label}</span>
              <input
                value={f.value}
                onChange={(e) => f.set(e.target.value)}
                placeholder={f.ph}
                inputMode="decimal"
                className="rounded-md border bg-background px-2 py-1.5"
              />
            </label>
          ))}
        </div>
      )}

      {err && <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-500">{err}</div>}

      {scope === "market" && !err && (
        <div className="text-xs text-muted-foreground">
          全市场档基于实时行情（whitelist 已剔 ST/退/科创/北交所），按换手降序取前 300，约 2~5 秒
        </div>
      )}

      {loading && !payload ? (
        <div className="flex items-center gap-2 p-8 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> 拉取行情中…
        </div>
      ) : payload && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-3 py-2">代码</th>
                <th className="px-3 py-2">名称</th>
                {scope !== "market" && <th className="px-3 py-2">分组</th>}
                <th className="px-3 py-2 text-right">现价</th>
                <th className="px-3 py-2 text-right">涨跌%</th>
                <th className="px-3 py-2 text-right">PE TTM</th>
                <th className="px-3 py-2 text-right">PB</th>
                <th className="px-3 py-2 text-right">市值(亿)</th>
                <th className="px-3 py-2 text-right">换手%</th>
                <th className="px-3 py-2 text-right">成交额</th>
                <th className="px-3 py-2 text-right">量比</th>
              </tr>
            </thead>
            <tbody>
              {payload.items.map((it) => (
                <tr key={it.code} className="border-b last:border-0 hover:bg-accent/40">
                  <td className="px-3 py-1.5 font-mono text-xs">{it.code}</td>
                  <td className="px-3 py-1.5">{it.name}</td>
                  {scope !== "market" && (
                    <td className="px-3 py-1.5">
                      {it.category && (
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs",
                            it.category === "holding"
                              ? "bg-red-500/10 text-red-500"
                              : it.category === "observation"
                                ? "bg-amber-500/10 text-amber-600"
                                : "bg-blue-500/10 text-blue-500",
                          )}
                        >
                          {CAT_LABEL[it.category] || it.category}
                        </span>
                      )}
                    </td>
                  )}
                  <td className="px-3 py-1.5 text-right">{it.price.toFixed(2)}</td>
                  <td
                    className={cn(
                      "px-3 py-1.5 text-right",
                      it.change_pct > 0 ? "text-red-500" : it.change_pct < 0 ? "text-green-500" : "",
                    )}
                  >
                    {it.change_pct.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right">{it.pe_ttm > 0 ? it.pe_ttm.toFixed(1) : "亏损"}</td>
                  <td className="px-3 py-1.5 text-right">{it.pb > 0 ? it.pb.toFixed(2) : "—"}</td>
                  <td className="px-3 py-1.5 text-right">{it.mcap_yi.toFixed(1)}</td>
                  <td className="px-3 py-1.5 text-right">{it.turnover_pct.toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtWan(it.amount_wan)}</td>
                  <td className="px-3 py-1.5 text-right">{it.vol_ratio > 0 ? it.vol_ratio.toFixed(2) : "—"}</td>
                </tr>
              ))}
              {payload.items.length === 0 && (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-muted-foreground">
                    无命中标的，放宽筛选条件试试
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

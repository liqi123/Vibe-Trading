import { useCallback, useEffect, useState } from "react";
import { BookOpen, CalendarDays, Loader2, Newspaper, Search, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import type { PriceBar } from "@/lib/api";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { cn } from "@/lib/utils";

interface Quote {
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
  limit_up: number;
  limit_down: number;
}

interface Financials {
  period: string;
  revenue: number;
  revenue_yoy: number;
  net_profit: number;
  net_profit_yoy: number;
  eps: number;
  bvps: number;
  roe: number;
  gross_margin: number;
  net_margin: number;
}

interface ValMetric {
  current: number;
  percentile: number;
  min: number;
  max: number;
  p50: number;
}

interface Valuation {
  period: string;
  metrics: { pe_ttm?: ValMetric; pb?: ValMetric };
}

interface Overview {
  available: boolean;
  error?: string;
  code: string;
  quote: Quote | null;
  financials: Financials | null;
  valuation: Valuation | null;
  failed: string[];
}

interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface AnalysisData {
  data?: {
    name?: string;
    current_price?: number;
    E?: number;
    X?: number;
    kline?: KlineBar[];
    indicators?: Record<string, number>;
    error?: string;
  };
}

interface ResearchRes {
  available: boolean;
  reports?: { title: string; org: string; date: string; rating: string; pdf: string }[];
  n?: number;
}

interface NewsItem {
  title: string;
  time?: string;
  source?: string;
  url?: string;
}

interface NewsRes {
  available: boolean;
  items?: { code: string; name: string; news: NewsItem[] }[];
  note?: string;
  error?: string;
}

interface CalendarRes {
  available: boolean;
  disclosure?: { period: string; rows: { code: string; name: string; date: string; period: string }[] };
  unlock?: { code: string; name: string; date: string; shares_yi: number; mv_yi: number; kind: string }[];
  note?: string;
}

type Tab = "news" | "research" | "calendar";

const fmtYi = (v?: number): string => (v == null ? "—" : `${(v / 1e8).toFixed(1)}亿`);
const fmtPct = (v?: number): string => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

function Tile({ label, value, cls }: { label: string; value: string | number; cls?: string }) {
  return (
    <div className="rounded-md border p-2 text-center">
      <div className={cn("font-mono text-sm font-semibold tabular-nums", cls)}>{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  );
}

function ValBar({ label, m }: { label: string; m: ValMetric }) {
  const pos = Math.max(0, Math.min(100, m.percentile));
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">
          {m.current?.toFixed(2)} · {pos.toFixed(0)}%分位
        </span>
      </div>
      <div className="relative h-2 rounded bg-muted">
        <div className="absolute inset-y-0 left-0 rounded bg-blue-500/60" style={{ width: `${pos}%` }} />
        <div className="absolute inset-y-0 w-px bg-muted-foreground/60" style={{ left: `${Math.min(100, ((m.p50 - m.min) / Math.max(1e-9, m.max - m.min)) * 100)}%` }} />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{m.min?.toFixed(1)}</span>
        <span>中位 {m.p50?.toFixed(1)}</span>
        <span>{m.max?.toFixed(1)}</span>
      </div>
    </div>
  );
}

export function StockDeepDive() {
  const [code, setCode] = useState("");
  const [query, setQuery] = useState("");
  const [ov, setOv] = useState<Overview | null>(null);
  const [kline, setKline] = useState<PriceBar[]>([]);
  const [ana, setAna] = useState<AnalysisData["data"] | null>(null);
  const [tab, setTab] = useState<Tab>("news");
  const [news, setNews] = useState<NewsRes | null>(null);
  const [research, setResearch] = useState<ResearchRes | null>(null);
  const [calendar, setCalendar] = useState<CalendarRes | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const loadTab = useCallback(async (c: string, t: Tab) => {
    try {
      if (t === "news") {
        setNews(await api.tools.get<NewsRes>(`/vibe/stats/news?codes=${encodeURIComponent(c)}&size=8`));
      } else if (t === "research") {
        setResearch(await api.tools.get<ResearchRes>(`/vibe/stats/research?code=${encodeURIComponent(c)}`));
      } else {
        setCalendar(await api.tools.get<CalendarRes>(`/vibe/stats/calendar?codes=${encodeURIComponent(c)}`));
      }
    } catch (e) {
      /* section shows empty */
    }
  }, []);

  const search = useCallback(
    async (c: string) => {
      const q = c.trim();
      if (!q) return;
      setLoading(true);
      setErr("");
      setOv(null);
      setKline([]);
      setAna(null);
      setNews(null);
      setResearch(null);
      setCalendar(null);
      try {
        const [o, a] = await Promise.all([
          api.tools.get<Overview>(`/vibe/stats/stock-overview?code=${encodeURIComponent(q)}`),
          api.tools.get<AnalysisData>(`/stock-analysis/${encodeURIComponent(q)}`),
        ]);
        if (!o.available) {
          setErr(o.error || "概览不可用");
        }
        setOv(o);
        const d = a.data;
        if (d && !d.error) {
          setAna(d);
          setKline(
            (d.kline || []).map((b) => ({
              time: b.date,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
              volume: b.volume,
            })),
          );
        }
        setCode(q);
        loadTab(q, "news");
      } catch (e) {
        setErr(String(e));
      } finally {
        setLoading(false);
      }
    },
    [loadTab],
  );

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("code");
    if (q) {
      setQuery(q);
      search(q);
    }
  }, [search]);

  const switchTab = (t: Tab) => {
    setTab(t);
    if (code) loadTab(code, t);
  };

  const name = ov?.quote?.name || ana?.name || "";
  const price = ov?.quote?.price ?? ana?.current_price;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <TrendingUp className="h-6 w-6 text-rose-500" />
          个股深挖
        </h1>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search(query)}
            placeholder="代码/名称，如 sh600519 或 600519"
            className="w-64 rounded-md border bg-background px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => search(query)}
            disabled={loading}
            className="flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-sm text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            深挖
          </button>
        </div>
      </div>

      {err && <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-500">{err}</div>}

      {loading && !ov && (
        <div className="flex items-center gap-2 p-8 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> 加载中…
        </div>
      )}

      {ov && (
        <>
          {/* 行情头 */}
          <section className="rounded-lg border p-4">
            <div className="mb-3 flex items-baseline gap-3">
              <span className="text-lg font-bold">{name || ov.code}</span>
              <span className="font-mono text-xs text-muted-foreground">{ov.code}</span>
              {price != null && (
                <span className={cn("font-mono text-2xl font-bold", ov.quote && ov.quote.change_pct > 0 ? "text-red-500" : ov.quote && ov.quote.change_pct < 0 ? "text-green-500" : "")}>
                  {price.toFixed(2)}
                </span>
              )}
              {ov.quote && (
                <span className={cn("font-mono", ov.quote.change_pct > 0 ? "text-red-500" : ov.quote.change_pct < 0 ? "text-green-500" : "")}>
                  {fmtPct(ov.quote.change_pct)}
                </span>
              )}
            </div>
            {ov.quote ? (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
                <Tile label="PE TTM" value={ov.quote.pe_ttm > 0 ? ov.quote.pe_ttm.toFixed(1) : "亏损"} />
                <Tile label="PB" value={ov.quote.pb > 0 ? ov.quote.pb.toFixed(2) : "—"} />
                <Tile label="市值(亿)" value={ov.quote.mcap_yi?.toFixed(0) ?? "—"} />
                <Tile label="流通(亿)" value={ov.quote.float_mcap_yi?.toFixed(0) ?? "—"} />
                <Tile label="换手%" value={ov.quote.turnover_pct?.toFixed(2) ?? "—"} />
                <Tile label="成交额" value={ov.quote.amount_wan >= 10000 ? `${(ov.quote.amount_wan / 10000).toFixed(1)}亿` : `${ov.quote.amount_wan?.toFixed(0)}万`} />
                <Tile label="量比" value={ov.quote.vol_ratio > 0 ? ov.quote.vol_ratio.toFixed(2) : "—"} />
                <Tile label="涨停/跌停" value={`${ov.quote.limit_up ?? "—"}/${ov.quote.limit_down ?? "—"}`} />
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">行情块不可用{ov.failed?.includes("quote") ? "（取数失败）" : ""}</div>
            )}
          </section>

          {/* K线图 */}
          {kline.length > 0 && (
            <section className="rounded-lg border p-4">
              <div className="mb-2 flex items-center justify-between text-sm font-medium">
                <span>K线（近 {kline.length} 日 · 前复权口径以库为准）</span>
                {ana?.E != null && ana.E > 0 && (
                  <span className="text-xs text-muted-foreground">
                    E价 {ana.E.toFixed(2)} · X价 {ana.X?.toFixed(2)}
                  </span>
                )}
              </div>
              <CandlestickChart data={kline} height={420} />
            </section>
          )}

          {/* 财务摘要 + 估值分位 */}
          <section className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border p-4">
              <div className="mb-2 text-sm font-medium">财务摘要{ov.financials?.period && <span className="ml-1 text-xs font-normal text-muted-foreground">（{ov.financials.period}）</span>}</div>
              {ov.financials ? (
                <div className="grid grid-cols-3 gap-2">
                  <Tile label="营收" value={fmtYi(ov.financials.revenue)} />
                  <Tile label="营收同比" value={fmtPct(ov.financials.revenue_yoy)} cls={ov.financials.revenue_yoy > 0 ? "text-red-500" : "text-green-500"} />
                  <Tile label="净利" value={fmtYi(ov.financials.net_profit)} />
                  <Tile label="净利同比" value={fmtPct(ov.financials.net_profit_yoy)} cls={ov.financials.net_profit_yoy > 0 ? "text-red-500" : "text-green-500"} />
                  <Tile label="ROE" value={`${ov.financials.roe?.toFixed(2) ?? "—"}%`} />
                  <Tile label="毛利率" value={`${ov.financials.gross_margin?.toFixed(2) ?? "—"}%`} />
                  <Tile label="净利率" value={`${ov.financials.net_margin?.toFixed(2) ?? "—"}%`} />
                  <Tile label="EPS" value={ov.financials.eps?.toFixed(2) ?? "—"} />
                  <Tile label="每股净资产" value={ov.financials.bvps?.toFixed(2) ?? "—"} />
                </div>
              ) : (
                <div className="p-3 text-sm text-muted-foreground">财务摘要不可用</div>
              )}
            </div>
            <div className="rounded-lg border p-4">
              <div className="mb-3 text-sm font-medium">估值分位{ov.valuation?.period && <span className="ml-1 text-xs font-normal text-muted-foreground">（{ov.valuation.period}）</span>}</div>
              {ov.valuation?.metrics?.pe_ttm || ov.valuation?.metrics?.pb ? (
                <div className="space-y-4">
                  {ov.valuation.metrics.pe_ttm && <ValBar label="PE TTM" m={ov.valuation.metrics.pe_ttm} />}
                  {ov.valuation.metrics.pb && <ValBar label="PB" m={ov.valuation.metrics.pb} />}
                </div>
              ) : (
                <div className="p-3 text-sm text-muted-foreground">估值分位不可用</div>
              )}
            </div>
          </section>

          {/* 资讯/研报/日历 */}
          <section className="rounded-lg border">
            <div className="flex border-b">
              {([
                { key: "news" as Tab, label: "资讯", icon: Newspaper },
                { key: "research" as Tab, label: "研报", icon: BookOpen },
                { key: "calendar" as Tab, label: "事件日历", icon: CalendarDays },
              ]).map((t) => (
                <button
                  key={t.key}
                  onClick={() => switchTab(t.key)}
                  className={cn(
                    "flex items-center gap-1.5 px-4 py-2.5 text-sm",
                    tab === t.key ? "border-b-2 border-rose-500 font-medium text-rose-500" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <t.icon className="h-4 w-4" />
                  {t.label}
                </button>
              ))}
            </div>
            <div className="p-4">
              {tab === "news" &&
                (!news ? (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                ) : !news.available ? (
                  <div className="text-sm text-muted-foreground">{news.error || news.note || "资讯不可用（可能缺 IWENCAI_API_KEY）"}</div>
                ) : (news.items || []).length === 0 || !(news.items || [])[0]?.news?.length ? (
                  <div className="text-sm text-muted-foreground">暂无资讯</div>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {(news.items || [])[0].news.map((n, i) => (
                      <li key={i} className="flex items-baseline gap-2">
                        <span className="text-xs text-muted-foreground">{n.time || ""}</span>
                        {n.url ? (
                          <a href={n.url} target="_blank" rel="noreferrer" className="hover:text-rose-500 hover:underline">
                            {n.title}
                          </a>
                        ) : (
                          <span>{n.title}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                ))}
              {tab === "research" &&
                (!research ? (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                ) : !research.available ? (
                  <div className="text-sm text-muted-foreground">研报不可用</div>
                ) : (research.reports || []).length === 0 ? (
                  <div className="text-sm text-muted-foreground">暂无研报</div>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {(research.reports || []).map((r, i) => (
                      <li key={i} className="flex items-baseline gap-2">
                        <span className="text-xs text-muted-foreground">{r.date}</span>
                        {r.pdf ? (
                          <a href={r.pdf} target="_blank" rel="noreferrer" className="hover:text-rose-500 hover:underline">
                            {r.title}
                          </a>
                        ) : (
                          <span>{r.title}</span>
                        )}
                        <span className="text-xs text-muted-foreground">{r.org}{r.rating ? ` · ${r.rating}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                ))}
              {tab === "calendar" &&
                (!calendar ? (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                ) : !calendar.available ? (
                  <div className="text-sm text-muted-foreground">日历不可用</div>
                ) : (
                  <div className="space-y-4 text-sm">
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">财报预约披露</div>
                      {(calendar.disclosure?.rows || []).length === 0 ? (
                        <div className="text-muted-foreground">无未来披露预约</div>
                      ) : (
                        <ul className="space-y-1">
                          {(calendar.disclosure?.rows || []).map((r, i) => (
                            <li key={i}>
                              {r.date} · {r.name} · {r.period}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">限售解禁</div>
                      {(calendar.unlock || []).length === 0 ? (
                        <div className="text-muted-foreground">未来 120 天无解禁</div>
                      ) : (
                        <ul className="space-y-1">
                          {(calendar.unlock || []).map((u, i) => (
                            <li key={i}>
                              {u.date} · {u.name} · {u.shares_yi?.toFixed(2)}亿股 / {u.mv_yi?.toFixed(1)}亿（{u.kind}）
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

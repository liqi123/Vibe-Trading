import { useCallback, useEffect, useState } from "react";
import { TrendingUp, RefreshCw, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Catalyst {
  tag: string;
  n: number;
  avg_chg: number;
  limit_count: number;
  up_count: number;
  score: number;
}
interface Stock {
  code: string;
  name: string;
  price: number;
  chg: number;
  auction_chg: number | null;
  yesterday_limit: boolean;
  concepts: string[];
  core_concepts?: string[];
  catalysts?: Catalyst[];
  industry_l1?: string;
  industry_l2?: string;
  industry_l3?: string;
}
interface TagStat {
  tag: string;
  count: number;
  avg_chg: number;
  strong_count: number;
}
interface Payload {
  ok?: boolean;
  min_pct?: number;
  sort_by?: string;
  tag_source?: "industry" | "concept";
  auction_date?: string;
  prev_date?: string;
  industry_date?: string;
  total?: number;
  limit_total?: number;
  auction_total?: number;
  tag_stats?: TagStat[];
  concept_strength?: Catalyst[];
  stocks?: Stock[];
  error?: string;
}
type TagSource = "industry" | "concept";

const PCT_PRESET = [3, 5, 7];
const AUCTION_PRESET = [0, 3, 5];
const TAG_SOURCE_PRESET: { value: TagSource; label: string }[] = [
  { value: "industry", label: "同花顺行业" },
  { value: "concept", label: "同花顺概念" },
];

export function Gainers() {
  const [pct, setPct] = useState(5);
  const [top, setTop] = useState(0);
  const [sortBy, setSortBy] = useState<"chg" | "auction_chg">("chg");
  const [auctionMin, setAuctionMin] = useState<number | null>(null);
  const [tagSource, setTagSource] = useState<TagSource>("industry");
  const [conceptKw, setConceptKw] = useState("");
  const [payload, setPayload] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        pct: String(pct),
        top: String(top),
        sort_by: sortBy,
        tag_source: tagSource,
      });
      if (auctionMin !== null) params.set("auction_min", String(auctionMin));
      const res = await api.tools.get<Payload>(`/gainers?${params.toString()}`);
      setPayload(res);
      if (!res.ok) setError(res.error ?? "扫描失败");
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [pct, top, sortBy, auctionMin, tagSource]);

  useEffect(() => { load(); }, [load]);

  const stocks = payload?.stocks ?? [];
  const tagLabel = tagSource === "industry" ? "行业" : "概念";
  const kw = conceptKw.trim().toLowerCase();
  const filtered = kw
    ? stocks.filter((s) => {
        const tags = [
          ...(s.core_concepts?.length ? s.core_concepts : s.concepts),
          ...(s.catalysts?.map((c) => c.tag) ?? []),
        ];
        return tags.some((c) => c.toLowerCase().includes(kw));
      })
    : stocks;
  const tagStats = payload?.tag_stats ?? [];
  const conceptStrength = payload?.concept_strength ?? [];

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2"><TrendingUp className="h-5 w-5" /> 实时涨幅猎手</h1>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">实时涨幅 ≥</span>
          <div className="flex items-center gap-1 border rounded-md p-1">
            {PCT_PRESET.map((p) => (
              <button
                key={p}
                onClick={() => setPct(p)}
                className={cn("px-2.5 py-1 text-sm rounded transition-colors",
                  pct === p ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
              >
                {p}%
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">竞价涨幅 ≥</span>
          <div className="flex items-center gap-1 border rounded-md p-1">
            {AUCTION_PRESET.map((p) => (
              <button
                key={p}
                onClick={() => setAuctionMin(p === 0 ? null : p)}
                className={cn("px-2.5 py-1 text-sm rounded transition-colors",
                  (auctionMin === null && p === 0) || auctionMin === p
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted")}
              >
                {p === 0 ? "不限" : `${p}%`}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">标签口径</span>
          <div className="flex items-center gap-1 border rounded-md p-1">
            {TAG_SOURCE_PRESET.map((t) => (
              <button
                key={t.value}
                onClick={() => {
                  if (t.value === tagSource) return;
                  setConceptKw("");
                  setTagSource(t.value);
                }}
                className={cn("px-2.5 py-1 text-sm rounded transition-colors",
                  tagSource === t.value ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">排序</span>
          <div className="flex items-center gap-1 border rounded-md p-1">
            <button
              onClick={() => setSortBy("chg")}
              className={cn("px-2.5 py-1 text-sm rounded transition-colors",
                sortBy === "chg" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
            >
              实时涨幅
            </button>
            <button
              onClick={() => setSortBy("auction_chg")}
              className={cn("px-2.5 py-1 text-sm rounded transition-colors",
                sortBy === "auction_chg" ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
            >
              竞价涨幅
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">条数</span>
          <select
            value={top}
            onChange={(e) => setTop(Number(e.target.value))}
            className="px-2.5 py-1.5 text-sm border rounded-md bg-background"
          >
            <option value={0}>全部</option>
            <option value={30}>前 30</option>
            <option value={50}>前 50</option>
            <option value={100}>前 100</option>
          </select>
        </div>

        <div className="flex flex-col gap-1 ml-auto">
          <span className="text-xs text-muted-foreground">{tagLabel}筛选</span>
          <input
            value={conceptKw}
            onChange={(e) => setConceptKw(e.target.value)}
            placeholder={`输入${tagLabel}关键词…`}
            className="px-2.5 py-1.5 text-sm border rounded-md bg-background"
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">实时涨幅 ≥{pct}%</p>
          <p className="mt-1 text-3xl font-bold text-primary">{payload?.total ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">总数</p>
        </div>
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">其中昨日涨停</p>
          <p className="mt-1 text-3xl font-bold text-red-500">{payload?.limit_total ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">涨停延续标的</p>
        </div>
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">竞价涨幅有数据</p>
          <p className="mt-1 text-3xl font-bold">{payload?.auction_total ?? "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">基准 {payload?.auction_date || "—"}</p>
        </div>
        <div className="rounded-lg bg-card border p-4">
          <p className="text-xs text-muted-foreground">实时基准日</p>
          <p className="mt-1 text-3xl font-bold">{payload?.prev_date ? payload.prev_date.slice(5).replace("-", "/") : "—"}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">昨日涨停判定基准</p>
        </div>
      </div>

      {(conceptStrength.length > 0 || tagStats.length > 0) && (
        <div className="rounded-lg border bg-card p-3 space-y-3">
          {conceptStrength.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-2">
                今日主线 · 全市场概念实时强度（板块均涨幅 / 涨停家数，点击筛选）
              </p>
              <div className="flex flex-wrap gap-1.5">
                {conceptStrength.slice(0, 12).map((s) => (
                  <button
                    key={s.tag}
                    onClick={() => setConceptKw((prev) => (prev === s.tag ? "" : s.tag))}
                    title={`成员 ${s.n} 家 · 均涨 ${s.avg_chg > 0 ? "+" : ""}${s.avg_chg.toFixed(2)}% · 涨停 ${s.limit_count} 只 · 上涨 ${s.up_count}/${s.n}`}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-2 py-1 text-xs border rounded transition-colors",
                      conceptKw === s.tag
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-orange-500/10 text-orange-600 border-orange-500/30 hover:bg-orange-500/20",
                    )}
                  >
                    <span>{s.tag}</span>
                    <span className={cn("font-mono", s.avg_chg >= 2 ? "text-red-600" : "text-red-500")}>
                      {s.avg_chg > 0 ? "+" : ""}{s.avg_chg.toFixed(2)}%
                    </span>
                    <span className="font-mono font-semibold text-red-500">{s.limit_count}板</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {tagStats.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-2">
                本榜领涨{tagLabel}（榜内聚合：家数 / 均涨幅 / 涨幅≥9%家数，点击筛选）
                {tagSource === "industry" && payload?.industry_date
                  ? ` · 行业分类采集日 ${payload.industry_date}`
                  : ""}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {tagStats.map((s) => (
                  <button
                    key={s.tag}
                    onClick={() => setConceptKw((prev) => (prev === s.tag ? "" : s.tag))}
                    title={`均涨 ${s.avg_chg > 0 ? "+" : ""}${s.avg_chg.toFixed(2)}%，涨幅≥9% ${s.strong_count} 只`}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-2 py-1 text-xs border rounded transition-colors",
                      conceptKw === s.tag
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-violet-500/10 text-violet-600 border-violet-500/30 hover:bg-violet-500/20",
                    )}
                  >
                    <span>{s.tag}</span>
                    <span className={cn("font-mono", conceptKw === s.tag ? "opacity-80" : "text-muted-foreground")}>
                      {s.count}
                    </span>
                    <span className={cn("font-mono font-semibold", s.avg_chg >= 7 ? "text-red-600" : "text-red-500")}>
                      {s.avg_chg > 0 ? "+" : ""}{s.avg_chg.toFixed(2)}%
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground"><Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" /></div>
      ) : error ? (
        <div className="border rounded-lg p-12 text-center"><p className="text-sm text-destructive">加载失败: {error}</p></div>
      ) : filtered.length === 0 ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <p className="text-sm">{kw ? `无匹配「${conceptKw}」${tagLabel}的股票` : "暂无符合条件的股票"}</p>
          <p className="mt-1 text-xs">当前非交易时段可能只有收盘价数据；竞价涨幅需先完成竞价采集</p>
        </div>
      ) : (
        <div className="border rounded-lg bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                <th className="whitespace-nowrap px-3 py-2 font-medium">排名</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium">代码</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium">名称</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium text-right">现价</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium text-right">实时涨幅</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium text-right">竞价涨幅</th>
                <th className="px-3 py-2 font-medium">所属{tagLabel}</th>
                <th className="px-3 py-2 font-medium">涨停诱因</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s, i) => (
                <tr key={s.code} className="border-b border-border/30 last:border-0">
                  <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{i + 1}</td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono text-xs text-muted-foreground">{s.code}</td>
                  <td className="px-3 py-2 whitespace-nowrap font-medium">{s.name}</td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono text-right">{s.price.toFixed(2)}</td>
                  <td className={cn("px-3 py-2 whitespace-nowrap font-mono text-right font-semibold",
                    s.chg >= 7 ? "text-red-600" : s.chg >= 5 ? "text-red-500" : "text-red-400")}>
                    +{s.chg.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono text-right">
                    {s.auction_chg != null ? (
                      <span className={cn("font-semibold", s.auction_chg >= 5 ? "text-violet-600" : s.auction_chg >= 3 ? "text-violet-500" : "text-muted-foreground")}>
                        {s.auction_chg > 0 ? "+" : ""}{s.auction_chg.toFixed(2)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground/50">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(s.core_concepts?.length ? s.core_concepts : s.concepts).map((c) => (
                        <button
                          key={c}
                          onClick={() => setConceptKw(c)}
                          title={[s.industry_l1, s.industry_l2, s.industry_l3].filter(Boolean).join(" › ") || undefined}
                          className="inline-block px-1.5 py-0.5 text-xs border rounded bg-violet-500/10 text-violet-600 border-violet-500/30 hover:bg-violet-500/20 transition-colors"
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {s.catalysts?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {s.catalysts.slice(0, 2).map((c) => (
                          <button
                            key={c.tag}
                            onClick={() => setConceptKw(c.tag)}
                            title={`成员 ${c.n} 家 · 均涨 ${c.avg_chg > 0 ? "+" : ""}${c.avg_chg.toFixed(2)}% · 涨停 ${c.limit_count} 只 · 上涨 ${c.up_count}/${c.n}`}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs border rounded bg-orange-500/10 text-orange-600 border-orange-500/30 hover:bg-orange-500/20 transition-colors"
                          >
                            <span>{c.tag}</span>
                            <span className="font-mono opacity-80">
                              {c.avg_chg > 0 ? "+" : ""}{c.avg_chg.toFixed(2)}%
                            </span>
                            {c.limit_count > 0 && (
                              <span className="font-mono font-semibold text-red-500">{c.limit_count}板</span>
                            )}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground/50">无板块效应</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {s.yesterday_limit && (
                      <span className="inline-block px-1.5 py-0.5 text-xs border rounded bg-danger/10 text-danger border-danger/30">昨日涨停</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">⚠ 实时行情来自腾讯API；「竞价涨幅」= 竞价价/昨收-1（需当日竞价采集完成）；「昨日涨停」经本地库判定。标签口径：同花顺行业取二级行业（stock_ths_industry，鼠标悬停可看三级链），同花顺概念取本榜最热的 2 个核心概念。「涨停诱因」= 用全市场实时行情滚动计算个股所属概念板块的强度（均涨幅 75% + 涨停密度 + 涨停家数），取板块在涨且个股未跑输板块的最强前 2 个题材，即当天最可能解释它大涨的原因；显示"无板块效应"表示没有上涨题材带它，多为个股独立行情，仅供参考。</p>
    </div>
  );
}
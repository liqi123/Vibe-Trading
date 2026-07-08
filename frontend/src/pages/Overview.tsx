import { useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingUp, TrendingDown, BarChart3, Gauge } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";

interface IndexData {
  code: string; name: string; price: number; change_pct: number;
  prev_close: number; open: number; high: number; low: number; volume: number;
}

interface SentimentData {
  cycle: string; sentiment_score: number; label: string;
  advance_decline_ratio: number; limit_ratio: number;
  up: number; down: number; total: number;
  limit_up: number; limit_down: number;
}

interface SectorItem {
  name: string; momentum: number; rank: number;
}

interface MomentumData {
  sectors: { top: SectorItem[]; bottom: SectorItem[] };
  concept_sectors: { top: SectorItem[]; bottom: SectorItem[] };
  ma_distribution: { above5: number; above10: number; above20: number; total: number };
  rsi_distribution: { oversold: number; normal: number; overbought: number };
}

const INDEXES = [
  { code: "sh000001", name: "上证指数" },
  { code: "sz399001", name: "深证成指" },
  { code: "sz399006", name: "创业板指" },
];

function formatPct(v: number) {
  return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
}

export function Overview() {
  const [data, setData] = useState<IndexData[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState("");
  const [sentiment, setSentiment] = useState<SentimentData | null>(null);
  const [momentum, setMomentum] = useState<MomentumData | null>(null);
  const mountedRef = useRef(true);
  const { t } = useTranslation();
  const indexName = (code: string) => {
    switch (code) {
      case "sh000001": return t("overview.indexSh");
      case "sz399001": return t("overview.indexSz");
      default: return t("overview.indexCy");
    }
  };

  const fetchData = async () => {
    try {
      const codes = INDEXES.map(i => i.code).join(",");
      const [prices, sentiment, momentum] = await Promise.all([
        api.tools.get<any>(`/prices?codes=${codes}`),
        api.tools.get<any>("/market/sentiment"),
        api.tools.get<any>("/market/momentum"),
      ]);

      if (!mountedRef.current) return;

      if (prices) {
        if (!mountedRef.current) return;
        setData(INDEXES.map(idx => {
          const p = prices.prices?.[idx.code] || {};
          return {
            code: idx.code, name: idx.name,
            price: p.price ?? 0, change_pct: p.change_pct ?? 0,
            prev_close: p.prev_close ?? 0, open: p.open ?? 0,
            high: p.high ?? 0, low: p.low ?? 0, volume: p.volume ?? 0,
          };
        }));
      }

      if (!mountedRef.current) return;

      if (sentiment?.sentiment_score != null) {
        if (!mountedRef.current) return;
        setSentiment(sentiment);
      }

      if (!mountedRef.current) return;

      if (momentum?.sectors) {
        if (!mountedRef.current) return;
        setMomentum(momentum);
      }

      if (!mountedRef.current) return;
      setLastUpdate(new Date().toLocaleTimeString("zh-CN"));
    } catch (e) { /* ignore */ }
    finally { if (mountedRef.current) setLoading(false); }
  };

  useEffect(() => {
    mountedRef.current = true;
    fetchData();
    const timer = setInterval(fetchData, 15000);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("overview.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("overview.subtitle")}</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && <span className="text-xs text-muted-foreground">{t("overview.updatedAt", { time: lastUpdate })}</span>}
          <button onClick={fetchData} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> {t("overview.refresh")}
          </button>
        </div>
      </div>

      {/* Index Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        {data.map(idx => {
          const isUp = idx.change_pct >= 0;
          return (
            <div key={idx.code} className="border rounded-lg p-5 bg-card space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-lg">{indexName(idx.code)}</h2>
                {isUp ? <TrendingUp className="h-5 w-5 text-red-500" /> : <TrendingDown className="h-5 w-5 text-green-500" />}
              </div>
              <div>
                <p className={`text-3xl font-bold ${isUp ? "text-red-600" : "text-green-600"}`}>{idx.price.toFixed(2)}</p>
                <p className={`text-sm font-medium ${isUp ? "text-red-600" : "text-green-600"}`}>{formatPct(idx.change_pct)}</p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div>{t("overview.open")} <span className="text-foreground font-medium">{idx.open.toFixed(2)}</span></div>
                <div>{t("overview.prevClose")} <span className="text-foreground font-medium">{idx.prev_close.toFixed(2)}</span></div>
                <div>{t("overview.high")} <span className="text-red-600 font-medium">{idx.high.toFixed(2)}</span></div>
                <div>{t("overview.low")} <span className="text-green-600 font-medium">{idx.low.toFixed(2)}</span></div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Market Sentiment */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="border rounded-lg p-5 bg-card">
          <div className="flex items-center gap-2 mb-4">
            <Gauge className="h-4 w-4 text-purple-500" />
            <h3 className="font-semibold">{t("overview.marketSentiment")}</h3>
          </div>
          {sentiment ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">{t("overview.sentimentScore")}</p>
                  <p className="text-3xl font-bold">{sentiment.sentiment_score}</p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-medium ${sentiment.cycle === "up" ? "text-red-500" : sentiment.cycle === "down" ? "text-green-500" : "text-muted-foreground"}`}>
                    {sentiment.cycle === "up" ? t("overview.cycleUp") : sentiment.cycle === "down" ? t("overview.cycleDown") : t("overview.cycleSideways")}
                  </p>
                  <p className="text-lg font-semibold">{sentiment.label}</p>
                </div>
              </div>
              <div className="h-2.5 bg-gradient-to-r from-green-500 via-yellow-400 to-red-500 rounded-full overflow-hidden relative">
                <div className="absolute top-0 bottom-0 w-1 bg-white shadow-md rounded"
                  style={{ left: `${sentiment.sentiment_score}%`, transform: "translateX(-50%)" }} />
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-muted/50 rounded p-3">
                  <p className="text-xs text-muted-foreground mb-1">{t("overview.advanceDeclineRatio")}</p>
                  <p className="text-lg font-bold">{sentiment.advance_decline_ratio.toFixed(2)}</p>
                  <p className="text-xs text-muted-foreground">{sentiment.up} / {sentiment.down}</p>
                </div>
                <div className="bg-muted/50 rounded p-3">
                  <p className="text-xs text-muted-foreground mb-1">{t("overview.limitUpDown")}</p>
                  <p className="text-lg font-bold">{sentiment.limit_ratio.toFixed(2)}</p>
                  <p className="text-xs"><span className="text-red-500">{sentiment.limit_up}</span> / <span className="text-green-500">{sentiment.limit_down}</span></p>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("overview.loading")}</p>
          )}
        </div>

        {/* Market Momentum */}
        <div className="border rounded-lg p-5 bg-card">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 className="h-4 w-4 text-orange-500" />
            <h3 className="font-semibold">{t("overview.marketMomentum")}</h3>
          </div>
          {momentum ? (
            <div className="space-y-4">
              {/* Industry Sectors */}
              <div>
                <p className="text-xs text-muted-foreground mb-1.5 font-medium">{t("overview.industrySectors")} <span className="text-[10px] opacity-60">· 腾讯</span></p>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    {momentum.sectors.top.slice(0, 4).map(s => (
                      <div key={s.name} className="flex justify-between text-xs">
                        <span className="truncate">{s.name}</span>
                        <span className={s.momentum >= 0 ? "text-red-600 font-medium font-mono" : "text-green-600 font-medium font-mono"}>{formatPct(s.momentum)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="space-y-1">
                    {momentum.sectors.bottom.slice(0, 4).map(s => (
                      <div key={s.name} className="flex justify-between text-xs">
                        <span className="truncate">{s.name}</span>
                        <span className={s.momentum >= 0 ? "text-red-600 font-medium font-mono" : "text-green-600 font-medium font-mono"}>{formatPct(s.momentum)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {/* Concept Sectors */}
              {momentum.concept_sectors && momentum.concept_sectors.top && (
                <div className="border-t pt-3">
                  <p className="text-xs text-muted-foreground mb-1.5 font-medium">{t("overview.conceptSectors")} <span className="text-[10px] opacity-60">· 同花顺</span></p>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      {momentum.concept_sectors.top.slice(0, 4).map(s => (
                        <div key={s.name} className="flex justify-between text-xs">
                          <span className="truncate">{s.name}</span>
                          <span className={s.momentum >= 0 ? "text-red-600 font-medium font-mono" : "text-green-600 font-medium font-mono"}>{formatPct(s.momentum)}</span>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-1">
                      {momentum.concept_sectors.bottom.slice(0, 4).map(s => (
                        <div key={s.name} className="flex justify-between text-xs">
                          <span className="truncate">{s.name}</span>
                          <span className={s.momentum >= 0 ? "text-red-600 font-medium font-mono" : "text-green-600 font-medium font-mono"}>{formatPct(s.momentum)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              {/* MA distribution */}
              {momentum.ma_distribution.total > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">{t("overview.aboveMaRatio")}</p>
                  {[
                    { label: "MA5", v: momentum.ma_distribution.above5, total: momentum.ma_distribution.total, color: "bg-blue-500" },
                    { label: "MA10", v: momentum.ma_distribution.above10, total: momentum.ma_distribution.total, color: "bg-indigo-500" },
                    { label: "MA20", v: momentum.ma_distribution.above20, total: momentum.ma_distribution.total, color: "bg-violet-500" },
                  ].map(bar => {
                    const pct = bar.total > 0 ? (bar.v / bar.total * 100).toFixed(1) : "0";
                    return (
                      <div key={bar.label} className="flex items-center gap-2 text-xs mb-1">
                        <span className="w-10 text-right font-mono">{bar.label}</span>
                        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                          <div className={`h-full ${bar.color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
                        </div>
                        <span className="w-14 text-right font-mono text-muted-foreground">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
              )}
              {/* RSI */}
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span>{t("overview.oversold")}: <span className="text-green-600">{momentum.rsi_distribution.oversold}</span></span>
                <span>{t("overview.normal")}: {momentum.rsi_distribution.normal}</span>
                <span>{t("overview.overbought")}: <span className="text-red-600">{momentum.rsi_distribution.overbought}</span></span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("overview.loading")}</p>
          )}
        </div>
      </div>
    </div>
  );
}

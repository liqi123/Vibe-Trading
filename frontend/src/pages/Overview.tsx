import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, TrendingDown, BarChart3, Gauge } from "lucide-react";

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

  const fetchData = async () => {
    try {
      const codes = INDEXES.map(i => i.code).join(",");
      const [priceRes, sentRes, momRes] = await Promise.all([
        fetch(`/tools/prices?codes=${codes}`),
        fetch("/tools/market/sentiment"),
        fetch("/tools/market/momentum"),
      ]);

      if (priceRes.ok) {
        const json = await priceRes.json();
        setData(INDEXES.map(idx => {
          const p = json.prices?.[idx.code] || {};
          return {
            code: idx.code, name: idx.name,
            price: p.price ?? 0, change_pct: p.change_pct ?? 0,
            prev_close: p.prev_close ?? 0, open: p.open ?? 0,
            high: p.high ?? 0, low: p.low ?? 0, volume: p.volume ?? 0,
          };
        }));
      }

      if (sentRes.ok) {
        const s = await sentRes.json();
        if (s && s.sentiment_score != null) setSentiment(s);
      }

      if (momRes.ok) {
        const m = await momRes.json();
        if (m && m.sectors) setMomentum(m);
      }

      setLastUpdate(new Date().toLocaleTimeString("zh-CN"));
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">大盘总览</h1>
          <p className="text-sm text-muted-foreground mt-1">实时指数 / 市场情绪 / 板块动量</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && <span className="text-xs text-muted-foreground">更新于 {lastUpdate}</span>}
          <button onClick={fetchData} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> 刷新
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
                <h2 className="font-semibold text-lg">{idx.name}</h2>
                {isUp ? <TrendingUp className="h-5 w-5 text-red-500" /> : <TrendingDown className="h-5 w-5 text-green-500" />}
              </div>
              <div>
                <p className={`text-3xl font-bold ${isUp ? "text-red-600" : "text-green-600"}`}>{idx.price.toFixed(2)}</p>
                <p className={`text-sm font-medium ${isUp ? "text-red-600" : "text-green-600"}`}>{formatPct(idx.change_pct)}</p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div>开盘 <span className="text-foreground font-medium">{idx.open.toFixed(2)}</span></div>
                <div>昨收 <span className="text-foreground font-medium">{idx.prev_close.toFixed(2)}</span></div>
                <div>最高 <span className="text-red-600 font-medium">{idx.high.toFixed(2)}</span></div>
                <div>最低 <span className="text-green-600 font-medium">{idx.low.toFixed(2)}</span></div>
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
            <h3 className="font-semibold">市场情绪</h3>
          </div>
          {sentiment ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-muted-foreground">评分</p>
                  <p className="text-3xl font-bold">{sentiment.sentiment_score}</p>
                </div>
                <div className="text-right">
                  <p className={`text-xs font-medium ${sentiment.cycle === "up" ? "text-red-500" : sentiment.cycle === "down" ? "text-green-500" : "text-muted-foreground"}`}>
                    {sentiment.cycle === "up" ? "上升期" : sentiment.cycle === "down" ? "下行期" : "震荡期"}
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
                  <p className="text-xs text-muted-foreground mb-1">涨跌比</p>
                  <p className="text-lg font-bold">{sentiment.advance_decline_ratio.toFixed(2)}</p>
                  <p className="text-xs text-muted-foreground">{sentiment.up} / {sentiment.down}</p>
                </div>
                <div className="bg-muted/50 rounded p-3">
                  <p className="text-xs text-muted-foreground mb-1">涨停/跌停</p>
                  <p className="text-lg font-bold">{sentiment.limit_ratio.toFixed(2)}</p>
                  <p className="text-xs"><span className="text-red-500">{sentiment.limit_up}</span> / <span className="text-green-500">{sentiment.limit_down}</span></p>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">加载中...</p>
          )}
        </div>

        {/* Market Momentum */}
        <div className="border rounded-lg p-5 bg-card">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 className="h-4 w-4 text-orange-500" />
            <h3 className="font-semibold">市场动量</h3>
          </div>
          {momentum ? (
            <div className="space-y-4">
              {/* Sectors */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-red-500 mb-1 font-medium">领涨板块</p>
                  <div className="space-y-1">
                    {momentum.sectors.top.slice(0, 4).map(s => (
                      <div key={s.name} className="flex justify-between text-xs">
                        <span className="truncate">{s.name}</span>
                        <span className="text-red-600 font-medium font-mono">{formatPct(s.momentum)}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs text-green-500 mb-1 font-medium">领跌板块</p>
                  <div className="space-y-1">
                    {momentum.sectors.bottom.slice(0, 4).map(s => (
                      <div key={s.name} className="flex justify-between text-xs">
                        <span className="truncate">{s.name}</span>
                        <span className="text-green-600 font-medium font-mono">{formatPct(s.momentum)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {/* MA distribution */}
              {momentum.ma_distribution.total > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">均线之上占比</p>
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
                <span>超卖: <span className="text-green-600">{momentum.rsi_distribution.oversold}</span></span>
                <span>正常: {momentum.rsi_distribution.normal}</span>
                <span>超买: <span className="text-red-600">{momentum.rsi_distribution.overbought}</span></span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">加载中...</p>
          )}
        </div>
      </div>
    </div>
  );
}

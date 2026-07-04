import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, TrendingDown, Activity, BarChart3 } from "lucide-react";

interface IndexData {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  prev_close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
}

interface SentimentData {
  cycle?: string;
  emotion?: string;
  phase?: string;
  updated_at?: string;
}

interface SectorData {
  name: string;
  momentum: number;
}

const INDEXES = [
  { code: "sh000001", name: "上证指数" },
  { code: "sz399001", name: "深证成指" },
  { code: "sz399006", name: "创业板指" },
];

export function Overview() {
  const [data, setData] = useState<IndexData[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [sentiment, setSentiment] = useState<SentimentData | null>(null);
  const [sectors, setSectors] = useState<SectorData[]>([]);

  const fetchData = async () => {
    try {
      const codes = INDEXES.map((i) => i.code).join(",");
      const [priceRes, sentRes, secRes] = await Promise.all([
        fetch(`/tools/prices?codes=${codes}`),
        fetch("/tools/expectations/sentiment"),
        fetch("/tools/sectors/momentum"),
      ]);

      if (priceRes.ok) {
        const json = await priceRes.json();
        const items: IndexData[] = INDEXES.map((idx) => {
          const p = json.prices?.[idx.code] || {};
          return {
            code: idx.code,
            name: idx.name,
            price: p.price ?? 0,
            change_pct: p.change_pct ?? 0,
            prev_close: p.prev_close ?? 0,
            open: p.open ?? 0,
            high: p.high ?? 0,
            low: p.low ?? 0,
            volume: p.volume ?? 0,
          };
        });
        setData(items);
      }

      if (sentRes.ok) {
        const s = await sentRes.json();
        if (s && Object.keys(s).length > 0) setSentiment(s);
      }

      if (secRes.ok) {
        const s = await secRes.json();
        setSectors(s.sectors || []);
      }

      setLastUpdate(new Date().toLocaleTimeString("zh-CN"));
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 10000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">大盘总览</h1>
          <p className="text-sm text-muted-foreground mt-1">上证 / 深证 / 创业板 实时指数</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-xs text-muted-foreground">更新于 {lastUpdate}</span>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
      </div>

      {/* Index Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        {data.map((idx) => {
          const isUp = idx.change_pct >= 0;
          return (
            <div key={idx.code} className="border rounded-lg p-5 bg-card space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-lg">{idx.name}</h2>
                {isUp ? (
                  <TrendingUp className="h-5 w-5 text-red-500" />
                ) : (
                  <TrendingDown className="h-5 w-5 text-green-500" />
                )}
              </div>
              <div>
                <p className={`text-3xl font-bold ${isUp ? "text-red-600" : "text-green-600"}`}>
                  {idx.price.toFixed(2)}
                </p>
                <p className={`text-sm font-medium ${isUp ? "text-red-600" : "text-green-600"}`}>
                  {isUp ? "+" : ""}{idx.change_pct.toFixed(2)}%
                </p>
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

      {/* Sentiment + Sectors row */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Market Sentiment */}
        <div className="border rounded-lg p-5 bg-card">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="h-4 w-4 text-purple-500" />
            <h3 className="font-semibold">市场情绪</h3>
          </div>
          {sentiment ? (
            <div className="space-y-3">
              {sentiment.cycle && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">周期</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    sentiment.cycle.includes("多") || sentiment.cycle.includes("牛")
                      ? "bg-red-100 text-red-700"
                      : "bg-green-100 text-green-700"
                  }`}>{sentiment.cycle}</span>
                </div>
              )}
              {sentiment.emotion && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">情绪</span>
                  <span className="text-sm font-medium">{sentiment.emotion}</span>
                </div>
              )}
              {sentiment.phase && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">阶段</span>
                  <span className="text-sm font-medium">{sentiment.phase}</span>
                </div>
              )}
              {sentiment.updated_at && (
                <p className="text-xs text-muted-foreground pt-2 border-t">更新于 {sentiment.updated_at}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无情绪数据</p>
          )}
        </div>

        {/* Sector Momentum */}
        <div className="border rounded-lg p-5 bg-card">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 className="h-4 w-4 text-orange-500" />
            <h3 className="font-semibold">板块动量</h3>
          </div>
          {sectors.length > 0 ? (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {sectors.slice(0, 15).map((s) => (
                <div key={s.name} className="flex items-center justify-between text-sm">
                  <span className="truncate">{s.name}</span>
                  <span className={`font-mono font-medium ${
                    s.momentum > 0 ? "text-red-600" : s.momentum < 0 ? "text-green-600" : "text-muted-foreground"
                  }`}>
                    {s.momentum > 0 ? "+" : ""}{(s.momentum * 100).toFixed(2)}%
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无板块数据</p>
          )}
        </div>
      </div>
    </div>
  );
}

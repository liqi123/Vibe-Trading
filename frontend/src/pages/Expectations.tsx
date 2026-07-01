import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus, Target, AlertTriangle, RefreshCw } from "lucide-react";

interface Expectation {
  code: string;
  name: string;
  buy_price: number;
  buy_date: string;
  expectation: {
    next_day: string;
    auction_vol: string;
    target_pct: number;
    stop_pct: number;
    confidence: string;
    score: number;
  };
  target_price: number;
  invalid_price: number;
  status: string;
  daily_records: any[];
}

interface SentimentState {
  cycle?: string;
  last_update?: string;
  notes?: string;
}

function getExpectationIcon(nextDay: string) {
  if (nextDay.includes("高开") || nextDay.includes("up")) return <TrendingUp className="h-4 w-4 text-green-500" />;
  if (nextDay.includes("低开") || nextDay.includes("down")) return <TrendingDown className="h-4 w-4 text-red-500" />;
  return <Minus className="h-4 w-4 text-yellow-500" />;
}

function getConfidenceColor(confidence: string) {
  if (confidence === "高") return "text-green-600 bg-green-50";
  if (confidence === "中") return "text-yellow-600 bg-yellow-50";
  return "text-red-600 bg-red-50";
}

export function Expectations() {
  const [data, setData] = useState<Expectation[]>([]);
  const [sentiment, setSentiment] = useState<SentimentState>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [expRes, sentRes] = await Promise.all([
        fetch("/tools/expectations"),
        fetch("/tools/expectations/sentiment"),
      ]);
      const expData = await expRes.json();
      const sentData = await sentRes.json();
      setData(expData.positions || []);
      setSentiment(sentData);
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">预期管理</h1>
          <p className="text-sm text-muted-foreground mt-1">买入预期记录与竞价检查</p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {/* Sentiment Card */}
      <div className="border rounded-lg p-4 bg-card">
        <h2 className="font-semibold mb-2 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          市场情绪周期
        </h2>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-muted-foreground">当前周期:</span>
          <span className="font-medium">{sentiment.cycle || "未设置"}</span>
          {sentiment.last_update && (
            <span className="text-muted-foreground">更新: {sentiment.last_update}</span>
          )}
        </div>
        {sentiment.notes && (
          <p className="text-sm text-muted-foreground mt-2">{sentiment.notes}</p>
        )}
      </div>

      {error && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Positions */}
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-48 rounded-lg bg-muted/50 animate-pulse" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          暂无持仓预期数据
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.map((pos) => (
            <div key={pos.code} className="border rounded-lg p-4 bg-card space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold">{pos.name}</h3>
                  <p className="text-xs text-muted-foreground">{pos.code}</p>
                </div>
                <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                  {pos.status}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-muted-foreground">买入价</span>
                  <p className="font-medium">{pos.buy_price?.toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">买入日期</span>
                  <p className="font-medium">{pos.buy_date}</p>
                </div>
              </div>

              {pos.expectation && (
                <div className="border-t pt-3 space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    {getExpectationIcon(pos.expectation.next_day)}
                    <span>预期: {pos.expectation.next_day}</span>
                    <span className="text-muted-foreground">|</span>
                    <span>量能: {pos.expectation.auction_vol}</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="text-muted-foreground">目标:</span>
                    <span className="text-green-600">+{(pos.expectation.target_pct * 100).toFixed(1)}%</span>
                    <span className="text-muted-foreground">止损:</span>
                    <span className="text-red-600">{(pos.expectation.stop_pct * 100).toFixed(1)}%</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <Target className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>目标价: {pos.target_price?.toFixed(2)}</span>
                    <span className="text-muted-foreground">|</span>
                    <span>失效价: {pos.invalid_price?.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">置信度:</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${getConfidenceColor(pos.expectation.confidence)}`}>
                      {pos.expectation.confidence}
                    </span>
                    <span className="text-xs text-muted-foreground">评分: {pos.expectation.score}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

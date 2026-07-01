import { useEffect, useState } from "react";
import { Search, RefreshCw, TrendingUp, Filter } from "lucide-react";

interface MarketStats {
  latest_date: string;
  stats: {
    total: number;
    up: number;
    down: number;
    flat: number;
  };
}

export function DailyScan() {
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/tools/market/overview");
      if (!res.ok) throw new Error("Failed to load market data");
      setMarket(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const stats = market?.stats;
  const upRatio = stats ? (stats.up / stats.total * 100).toFixed(1) : "0";
  const downRatio = stats ? (stats.down / stats.total * 100).toFixed(1) : "0";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">每日选股</h1>
          <p className="text-sm text-muted-foreground mt-1">策略扫描与市场概览</p>
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

      {error && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Market Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">最新日期</div>
          <p className="text-xl font-bold">{market?.latest_date || "-"}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-green-500" />
            上涨
          </div>
          <p className="text-xl font-bold text-green-600">{stats?.up || 0}</p>
          <p className="text-xs text-muted-foreground">{upRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-red-500 rotate-180" />
            下跌
          </div>
          <p className="text-xl font-bold text-red-600">{stats?.down || 0}</p>
          <p className="text-xs text-muted-foreground">{downRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">总数</div>
          <p className="text-xl font-bold">{stats?.total || 0}</p>
        </div>
      </div>

      {/* Market Breadth Bar */}
      {stats && stats.total > 0 && (
        <div className="border rounded-lg p-4 bg-card">
          <h2 className="font-semibold mb-3">市场宽度</h2>
          <div className="flex h-6 rounded-full overflow-hidden bg-muted">
            <div
              className="bg-green-500 transition-all"
              style={{ width: `${(stats.up / stats.total) * 100}%` }}
              title={`上涨 ${stats.up}`}
            />
            <div
              className="bg-gray-400 transition-all"
              style={{ width: `${(stats.flat / stats.total) * 100}%` }}
              title={`平盘 ${stats.flat}`}
            />
            <div
              className="bg-red-500 transition-all"
              style={{ width: `${(stats.down / stats.total) * 100}%` }}
              title={`下跌 ${stats.down}`}
            />
          </div>
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span className="text-green-600">上涨 {stats.up}</span>
            <span>平盘 {stats.flat}</span>
            <span className="text-red-600">下跌 {stats.down}</span>
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="border rounded-lg p-4 bg-card">
        <h2 className="font-semibold mb-3">快速操作</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <a
            href="python strategies/daily_check.py"
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors"
          >
            <Search className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">V1 斐波那契选股</p>
              <p className="text-xs text-muted-foreground">daily_check.py</p>
            </div>
          </a>
          <a
            href="python strategies/daily_check_v5.py"
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors"
          >
            <Filter className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">V5 趋势选股</p>
              <p className="text-xs text-muted-foreground">daily_check_v5.py</p>
            </div>
          </a>
          <a
            href="python -m utils stops"
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors"
          >
            <TrendingUp className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">止损检查</p>
              <p className="text-xs text-muted-foreground">python -m utils stops</p>
            </div>
          </a>
        </div>
      </div>
    </div>
  );
}

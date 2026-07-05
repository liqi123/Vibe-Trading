import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, BarChart3, PieChart } from "lucide-react";

interface VolumeStock {
  code: string; name: string; price: number; chg_pct: number;
  amount: number; volume: number; industry: string;
  high: number; low: number; open: number;
}

interface IndustryRank {
  industry: string; total_amount: number; pct: number;
}

interface VolumeStats {
  total_stocks: number; total_amount: number;
  top_amount: number; top_name: string;
}

export function VolumeRank() {
  const [stocks, setStocks] = useState<VolumeStock[]>([]);
  const [byIndustry, setByIndustry] = useState<Record<string, VolumeStock[]>>({});
  const [industryRanking, setIndustryRanking] = useState<IndustryRank[]>([]);
  const [stats, setStats] = useState<VolumeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"list" | "industry">("list");

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch("/tools/market/volume-rank?limit=50");
      if (res.ok) {
        const data = await res.json();
        setStocks(data.stocks || []);
        setByIndustry(data.by_industry || {});
        setIndustryRanking(data.industry_ranking || []);
        setStats(data.stats || null);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const formatAmount = (v: number) => {
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
    return String(v);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            成交额排行
          </h1>
          <p className="text-sm text-muted-foreground mt-1">全市场成交额TOP 50，按行业聚类分析资金流向</p>
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

      {/* Stats Cards */}
      {stats && (
        <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">统计个数</div>
            <p className="text-xl font-bold">{stats.total_stocks}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">总成交额</div>
            <p className="text-xl font-bold">{formatAmount(stats.total_amount)}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">第一名</div>
            <p className="text-lg font-bold truncate">{stats.top_name}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">第一成交额</div>
            <p className="text-xl font-bold">{formatAmount(stats.top_amount)}</p>
          </div>
        </div>
      )}

      {/* Industry Concentration Bar */}
      {industryRanking.length > 0 && (
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 mb-3">
            <PieChart className="h-4 w-4 text-muted-foreground" />
            <h2 className="font-semibold">行业资金集中度</h2>
          </div>
          <div className="space-y-2">
            {industryRanking.slice(0, 10).map((ind) => (
              <div key={ind.industry} className="flex items-center gap-3 text-sm">
                <span className="w-20 truncate text-right">{ind.industry}</span>
                <div className="flex-1 h-5 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all"
                    style={{ width: `${Math.min(ind.pct, 100)}%` }}
                  />
                </div>
                <span className="w-24 text-right font-mono text-xs">{formatAmount(ind.total_amount)}</span>
                <span className="w-12 text-right text-xs text-muted-foreground">{ind.pct}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* View Toggle */}
      <div className="flex items-center gap-1 border-b">
        {[
          { key: "list" as const, label: "成交额排行", icon: BarChart3 },
          { key: "industry" as const, label: "按行业聚类", icon: TrendingUp },
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
              view === key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {loading && stocks.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground">加载中...</div>
      ) : view === "list" ? (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">涨跌幅</th>
                  <th className="px-3 py-2 text-right font-medium">成交额</th>
                  <th className="px-3 py-2 text-right font-medium">成交量</th>
                  <th className="px-3 py-2 text-left font-medium">行业</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s, i) => {
                  const isLimitUp = s.chg_pct >= 9.5;
                  const isLimitDown = s.chg_pct <= -9.5;
                  return (
                    <tr key={s.code} className="border-t hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{s.code.replace(/^(sh|sz)/, "")}</td>
                      <td className="px-3 py-2 font-medium">{s.name}</td>
                      <td className="px-3 py-2 text-right font-mono">{s.price.toFixed(2)}</td>
                      <td className={`px-3 py-2 text-right font-medium ${isLimitUp ? "text-red-600" : isLimitDown ? "text-green-600" : s.chg_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {s.chg_pct >= 0 ? "+" : ""}{s.chg_pct.toFixed(2)}%
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-medium">{formatAmount(s.amount)}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{(s.volume / 10000).toFixed(0)}万</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{s.industry || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Industry view */
        <div className="space-y-4">
          {Object.entries(byIndustry).sort(([, a], [, b]) => {
            const sumA = a.reduce((s, x) => s + x.amount, 0);
            const sumB = b.reduce((s, x) => s + x.amount, 0);
            return sumB - sumA;
          }).map(([industry, stocks]) => {
            const totalAmt = stocks.reduce((s, x) => s + x.amount, 0);
            return (
              <div key={industry} className="border rounded-lg bg-card overflow-hidden">
                <div className="px-4 py-2 border-b bg-muted/30 flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-primary" />
                  <span className="font-medium">{industry}</span>
                  <span className="text-xs text-muted-foreground">{stocks.length}只</span>
                  <span className="text-xs font-mono ml-auto">{formatAmount(totalAmt)}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">代码</th>
                        <th className="px-3 py-2 text-left font-medium">名称</th>
                        <th className="px-3 py-2 text-right font-medium">现价</th>
                        <th className="px-3 py-2 text-right font-medium">涨跌幅</th>
                        <th className="px-3 py-2 text-right font-medium">成交额</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stocks.map((s) => (
                        <tr key={s.code} className="border-t hover:bg-muted/30">
                          <td className="px-3 py-2 font-mono">{s.code.replace(/^(sh|sz)/, "")}</td>
                          <td className="px-3 py-2">{s.name}</td>
                          <td className="px-3 py-2 text-right font-mono">{s.price.toFixed(2)}</td>
                          <td className={`px-3 py-2 text-right font-medium ${s.chg_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {s.chg_pct > 0 ? "+" : ""}{s.chg_pct.toFixed(2)}%
                          </td>
                          <td className="px-3 py-2 text-right font-mono">{formatAmount(s.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

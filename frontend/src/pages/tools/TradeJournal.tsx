import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

interface Trade {
  date: string;
  code: string;
  name: string;
  action: string;
  price: number;
  shares: number;
  reason?: string;
}

interface Stats {
  total: number;
  closed: number;
  winning: number;
  losing: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export function TradeJournal() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [weekly, setWeekly] = useState("");
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"trades" | "stats" | "weekly">("trades");

  const fetchData = async () => {
    setLoading(true);
    try {
      const [jData, wData] = await Promise.all([
        api.tools.get<any>("/journal?days=90"),
        api.tools.get<any>("/journal/weekly"),
      ]);
      setTrades(jData.trades || []);
      setStats(jData.stats || null);
      setWeekly(wData.report || "");
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">交易日志</h1>
          <p className="text-sm text-muted-foreground mt-1">交易记录与统计分析</p>
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />刷新
        </button>
      </div>

      <div className="flex gap-2 border-b">
        {(["trades", "stats", "weekly"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}>
            {t === "trades" ? "交易记录" : t === "stats" ? "统计数据" : "周报"}
          </button>
        ))}
      </div>

      {tab === "trades" && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">日期</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-left font-medium">操作</th>
                  <th className="px-4 py-2 text-right font-medium">价格</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-left font-medium">原因</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂无记录</td></tr>
                ) : trades.map((t, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2 text-muted-foreground">{t.date}</td>
                    <td className="px-4 py-2 font-mono text-xs">{t.code}</td>
                    <td className="px-4 py-2">{t.name}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.action === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                      }`}>
                        {t.action === "buy" ? "买入" : "卖出"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">{t.price?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right">{t.shares}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{t.reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "stats" && stats && (
        <div className="grid gap-4 md:grid-cols-4">
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">总交易</div>
            <p className="text-2xl font-bold">{stats.total}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">胜率</div>
            <p className="text-2xl font-bold text-red-600">{stats.win_rate ? (stats.win_rate * 100).toFixed(1) : 0}%</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">总盈亏</div>
            <p className={`text-2xl font-bold ${(stats.total_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
              {(stats.total_pnl || 0) >= 0 ? "+" : ""}{(stats.total_pnl || 0).toFixed(2)}
            </p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">平均盈亏</div>
            <p className={`text-2xl font-bold ${(stats.avg_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
              {(stats.avg_pnl || 0).toFixed(2)}
            </p>
          </div>
        </div>
      )}

      {tab === "weekly" && (
        <div className="border rounded-lg bg-card p-5">
          <pre className="text-sm whitespace-pre-wrap font-mono">{weekly || "暂无周报数据"}</pre>
        </div>
      )}
    </div>
  );
}

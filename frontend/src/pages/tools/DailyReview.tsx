import { useEffect, useState, useCallback } from "react";
import { RefreshCw, TrendingUp, Wallet, BookOpen, BarChart3, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import { api } from "@/lib/api";

function localDate(date?: Date): string {
  const d = date || new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

interface MarketStats {
  total: number; up: number; down: number; flat: number;
  limit_up: number; limit_down: number;
}

interface Position {
  code: string; name: string; buy_price: number; shares: number;
  cost: number; current_price: number;
  E?: number; stop?: number; highest?: number; score?: number;
}

interface PaperState {
  name?: string; initial_capital: number; cash: number;
  positions: Position[]; history?: any[];
}

interface JournalEntry {
  date: string; action: string; code: string;
  name?: string; price?: number; shares?: number; pnl?: number; reason?: string;
}

function pnlClass(v: number) {
  if (v > 0) return "text-red-600";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function formatMoney(v: number) {
  return v.toLocaleString("zh-CN", { style: "currency", currency: "CNY" });
}

function PosCard({ title, state, color }: { title: string; state: PaperState | null; color: string }) {
  const positions = state?.positions || [];
  const cash = state?.cash || 0;
  const marketValue = positions.reduce((s, p) => s + (p.current_price || p.buy_price) * p.shares, 0);
  const totalValue = cash + marketValue;
  const totalReturn = state?.initial_capital ? (totalValue - state.initial_capital) / state.initial_capital : 0;

  return (
    <div className="border rounded-lg p-4 bg-card">
      <h3 className="font-semibold mb-3 flex items-center gap-2">
        <Wallet className={`h-4 w-4 ${color}`} />
        {title}
      </h3>
      <div className="grid grid-cols-3 gap-3 text-sm mb-3">
        <div>
          <span className="text-muted-foreground">持仓</span>
          <p className="font-bold text-lg">{positions.length} / 5</p>
        </div>
        <div>
          <span className="text-muted-foreground">总资产</span>
          <p className="font-bold text-lg">{formatMoney(totalValue)}</p>
        </div>
        <div>
          <span className="text-muted-foreground">收益率</span>
          <p className={`font-bold text-lg ${pnlClass(totalReturn)}`}>
            {(totalReturn * 100).toFixed(1)}%
          </p>
        </div>
      </div>
      {positions.length > 0 && (
        <div className="space-y-1.5">
          {positions.map((p) => {
            const avgCost = p.shares > 0 ? p.cost / p.shares : 0;
            const pnl = avgCost > 0 ? ((p.current_price || p.buy_price) - avgCost) / avgCost : 0;
            return (
              <div key={p.code} className="flex items-center justify-between text-xs py-1 border-b last:border-0">
                <span className="font-mono">{p.code} {p.name}</span>
                <span className="text-muted-foreground">{avgCost.toFixed(2)} → {(p.current_price || 0).toFixed(2)}</span>
                <span className={`font-medium ${pnlClass(pnl)}`}>{(pnl * 100).toFixed(1)}%</span>
              </div>
            );
          })}
        </div>
      )}
      {positions.length === 0 && (
        <p className="text-xs text-muted-foreground">空仓</p>
      )}
    </div>
  );
}

export function DailyReview() {
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [v1, setV1] = useState<PaperState | null>(null);
  const [v5, setV5] = useState<PaperState | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [report, setReport] = useState<string | null>(null);

  useEffect(() => {
    const today = localDate();
    const ctrl = new AbortController();
    api.tools.get<any>(`/review-report?date=${today}`, ctrl.signal)
      .then(d => { if (d?.content) setReport(d.content); })
      .catch(() => {
        if (!ctrl.signal.aborted) {
          const cached = localStorage.getItem(`review_report_${today}`);
          if (cached) setReport(cached);
        }
      });
    return () => ctrl.abort();
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [rM, r1, r5, rJ, t1, t5] = await Promise.all([
        api.tools.get<any>("/market/realtime"),
        api.tools.get<any>("/portfolio"),
        api.tools.get<any>("/portfolio/v5"),
        api.tools.get<any>("/journal?days=1"),
        api.tools.get<any>("/trades"),
        api.tools.get<any>("/trades/v5"),
      ]);
      setMarket(rM);
      setV1(r1);
      setV5(r5);
      setJournal(rJ.trades || []);
      const d1 = t1 || { history: [] };
      const d5 = t5 || { history: [] };
      setTrades([
        ...(d1.history || []).map((t: any) => ({ ...t, strategy: "V1" })),
        ...(d5.history || []).map((t: any) => ({ ...t, strategy: "V5" })),
      ]);
    } catch (e) { console.error("DailyReview fetchAll", e); }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const stats = market;
  const upRatio = stats && stats.total ? (stats.up / stats.total * 100).toFixed(1) : "0";
  const downRatio = stats && stats.total ? (stats.down / stats.total * 100).toFixed(1) : "0";

  const generateReport = useCallback(async () => {
    setGenerating(true);
    setReport(null);
    try {
      const { task_id } = await api.tools.post<any>("/run-script", { script: "review_v5" });

      let output = "";
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const data = await api.tools.get<any>(`/run-script/${task_id}`);
        output = data.output || "";
        if (output.includes("执行完成") || output.includes("错误") || output.includes("超时")) break;
      }

      const body = output.replace(/^\[.*?\] 执行完成 \(exit=\d+\)\s*\n\n?/, "").trim();
      const result = body || output;

      if (!result || result.includes("401") || result.includes("Unauthorized") || result.includes("查询失败")) {
        await loadExistingReport();
      } else {
        setReport(result);
        const today = localDate();
        localStorage.setItem(`review_report_${today}`, result);
      }
    } catch (e) {
      await loadExistingReport();
    } finally {
      setGenerating(false);
    }
  }, []);

  // 从后端加载已有的复盘报告
  const loadExistingReport = async () => {
    try {
      const today = localDate();
      const d = await api.tools.get<any>(`/review-report?date=${today}`);
      if (d?.content) {
        setReport(d.content);
        localStorage.setItem(`review_report_${today}`, d.content);
        return;
      }
      const cached = localStorage.getItem(`review_report_${today}`);
      if (cached) { setReport(cached); return; }
      setReport("生成失败，且无已有报告可展示");
    } catch { /* ignore */ }
  };

  const todayTrades = journal.filter(t => t.action === "sell" || t.action === "buy");
  const sells = todayTrades.filter(t => t.action === "sell");
  const buys = todayTrades.filter(t => t.action === "buy");

  const allTrades = trades;
  const closedTrades = allTrades.filter((t: any) => t.action === "sell" && t.pnl != null);
  const winCount = closedTrades.filter((t: any) => t.pnl > 0).length;
  const winRate = closedTrades.length > 0 ? (winCount / closedTrades.length * 100).toFixed(1) : "0";
  const totalPnl = closedTrades.reduce((s: number, t: any) => s + (t.pnl || 0), 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">每日复盘</h1>
          <p className="text-sm text-muted-foreground mt-1">今日市场、持仓回顾、交易统计</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchAll} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
      </div>

      {/* Market Stats */}
      <div className="border rounded-lg p-4 bg-card">
        <h2 className="font-semibold mb-3 flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          今日市场
        </h2>
        <div className="grid gap-3 md:grid-cols-6">
          <div>
            <div className="text-xs text-muted-foreground">总数</div>
            <p className="text-lg font-bold">{stats?.total || 0}</p>
          </div>
          <div>
            <div className="text-xs text-red-500">上涨</div>
            <p className="text-lg font-bold text-red-600">{stats?.up || 0}</p>
            <p className="text-xs text-muted-foreground">{upRatio}%</p>
          </div>
          <div>
            <div className="text-xs text-green-500">下跌</div>
            <p className="text-lg font-bold text-green-600">{stats?.down || 0}</p>
            <p className="text-xs text-muted-foreground">{downRatio}%</p>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">平盘</div>
            <p className="text-lg font-bold">{stats?.flat || 0}</p>
          </div>
          <div>
            <div className="text-xs text-red-500">涨停</div>
            <p className="text-lg font-bold text-red-600">{stats?.limit_up || 0}</p>
          </div>
          <div>
            <div className="text-xs text-green-500">跌停</div>
            <p className="text-lg font-bold text-green-600">{stats?.limit_down || 0}</p>
          </div>
        </div>
        {stats && stats.total > 0 && (
          <div className="flex h-2 rounded-full overflow-hidden bg-muted mt-3">
            <div className="bg-red-500 transition-all" style={{ width: `${(stats.up / stats.total) * 100}%` }} />
            <div className="bg-gray-400 transition-all" style={{ width: `${((stats.flat || 0) / stats.total) * 100}%` }} />
            <div className="bg-green-500 transition-all" style={{ width: `${(stats.down / stats.total) * 100}%` }} />
          </div>
        )}
      </div>

      {/* Positions */}
      <div className="grid gap-4 md:grid-cols-2">
        <PosCard title="V1 斐波那契" state={v1} color="text-blue-500" />
        <PosCard title="V5 趋势" state={v5} color="text-purple-500" />
      </div>

      {/* Today's Trades */}
      <div className="grid gap-4 md:grid-cols-4">
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">今日交易</div>
          <p className="text-2xl font-bold">{todayTrades.length}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-green-500 mb-1">买入</div>
          <p className="text-2xl font-bold text-green-600">{buys.length}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-red-500 mb-1">卖出</div>
          <p className="text-2xl font-bold text-red-600">{sells.length}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">累计盈亏</div>
          <p className={`text-2xl font-bold ${pnlClass(totalPnl)}`}>{formatMoney(totalPnl)}</p>
          <p className="text-xs text-muted-foreground">胜率 {winRate}% ({winCount}/{closedTrades.length})</p>
        </div>
      </div>

      {/* Today's Journal */}
      {todayTrades.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            <h2 className="font-semibold">今日交易明细</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">时间</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-left font-medium">操作</th>
                  <th className="px-4 py-2 text-right font-medium">价格</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-right font-medium">盈亏</th>
                  <th className="px-4 py-2 text-left font-medium">原因</th>
                </tr>
              </thead>
              <tbody>
                {todayTrades.map((t, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{t.date}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{t.code}</td>
                    <td className="px-4 py-2.5">{t.name || "-"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.action === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                      }`}>
                        {t.action === "buy" ? "买入" : "卖出"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">{t.price?.toFixed(2) || "-"}</td>
                    <td className="px-4 py-2.5 text-right">{t.shares || "-"}</td>
                    <td className={`px-4 py-2.5 text-right font-medium ${t.pnl != null ? pnlClass(t.pnl) : "text-muted-foreground"}`}>
                      {t.pnl != null ? formatMoney(t.pnl) : "-"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{t.reason || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent closed trades */}
      {closedTrades.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            <h2 className="font-semibold">近期已平仓交易</h2>
            <span className="text-xs text-muted-foreground">({closedTrades.length} 笔, 胜率 {winRate}%)</span>
          </div>
          <div className="overflow-x-auto max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">日期</th>
                  <th className="px-4 py-2 text-left font-medium">策略</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-right font-medium">盈亏</th>
                  <th className="px-4 py-2 text-left font-medium">原因</th>
                </tr>
              </thead>
              <tbody>
                {closedTrades.slice(0, 30).map((t: any, i: number) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2 text-muted-foreground whitespace-nowrap">{t.date}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.strategy === "V1" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"
                      }`}>{t.strategy}</span>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">{t.code}</td>
                    <td className="px-4 py-2">{t.name || "-"}</td>
                    <td className={`px-4 py-2 text-right font-medium ${pnlClass(t.pnl)}`}>
                      {t.pnl != null ? formatMoney(t.pnl) : "-"}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{t.reason || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Report */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <FileText className="h-4 w-4" />
            复盘报告
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={generateReport}
              disabled={generating}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${generating ? "animate-spin" : ""}`} />
              {generating ? "生成中..." : (report ? "生成新报告" : "生成")}
            </button>
          </div>
        </div>
        {report ? (
          <div className="relative">
            <button
              onClick={() => { navigator.clipboard.writeText(report); }}
              className="absolute top-2 right-2 z-10 text-xs px-2 py-1 border rounded hover:bg-muted"
            >
              复制
            </button>
            <div className="p-4 text-sm overflow-auto max-h-[600px] leading-relaxed prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{report}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            <FileText className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">点击上方「生成」按钮生成今日复盘报告</p>
          </div>
        )}
      </div>

      {todayTrades.length === 0 && closedTrades.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          <p>暂无今日交易数据</p>
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { Wallet, History, RefreshCw, Clock } from "lucide-react";

interface V1Position {
  code: string;
  name: string;
  buy_price: number;
  shares: number;
  cost: number;
  E: number;
  stop: number;
  current_price: number;
}

interface V5Position {
  code: string;
  name: string;
  buy_price: number;
  shares: number;
  cost: number;
  current_price: number;
  highest: number;
  score: number;
}

interface PendingOrder {
  code: string;
  name?: string;
  action?: string;
  date?: string;
  note?: string;
}

interface TradeRecord {
  date: string;
  action: string;
  code: string;
  name?: string;
  price?: number;
  shares?: number;
  pnl?: number;
  note?: string;
  score?: number;
}

interface PaperState {
  name?: string;
  strategy?: string;
  initial_capital: number;
  cash: number;
  positions: V1Position[] | V5Position[];
  pending_orders?: PendingOrder[];
  history?: TradeRecord[];
}

function formatMoney(v: number) {
  return v.toLocaleString("zh-CN", { style: "currency", currency: "CNY" });
}

function formatPct(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function pnlClass(v: number) {
  if (v > 0) return "text-red-600";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function isV1(p: any): p is V1Position {
  return "E" in p;
}

export function PaperTrading() {
  const [v1, setV1] = useState<PaperState | null>(null);
  const [v5, setV5] = useState<PaperState | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"v1" | "v5">("v1");

  const fetchData = async () => {
    setLoading(true);
    try {
      const [r1, r5] = await Promise.all([
        fetch("/tools/portfolio"),
        fetch("/tools/portfolio/v5"),
      ]);
      setV1(await r1.json());
      setV5(await r5.json());
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  const state = activeTab === "v1" ? v1 : v5;
  const positions = state?.positions || [];
  const cash = state?.cash || 0;
  const initial = state?.initial_capital || 200000;

  const marketValue = positions.reduce((s, p) => s + (p.current_price || p.buy_price) * p.shares, 0);
  const totalCost = positions.reduce((s, p) => s + p.cost, 0);
  const totalPnl = marketValue - totalCost;
  const totalValue = cash + marketValue;
  const totalReturn = (totalValue - initial) / initial;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">模拟盘</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {state?.name || (activeTab === "v1" ? "斐波那契策略" : "趋势策略")}
          </p>
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

      {/* Tabs */}
      <div className="flex gap-2 border-b">
        {(["v1", "v5"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "v1" ? "V1 斐波那契" : "V5 趋势"}
          </button>
        ))}
      </div>

      {/* Summary */}
      <div className="grid gap-4 md:grid-cols-5">
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Wallet className="h-4 w-4" />
            总资产
          </div>
          <p className="text-xl font-bold">{formatMoney(totalValue)}</p>
          <p className={`text-xs ${pnlClass(totalReturn)}`}>{formatPct(totalReturn)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">可用现金</div>
          <p className="text-xl font-bold">{formatMoney(cash)}</p>
          <p className="text-xs text-muted-foreground">占比 {(cash / totalValue * 100).toFixed(1)}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">持仓市值</div>
          <p className="text-xl font-bold">{formatMoney(marketValue)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">持仓盈亏</div>
          <p className={`text-xl font-bold ${pnlClass(totalPnl)}`}>{formatMoney(totalPnl)}</p>
          <p className={`text-xs ${pnlClass(totalPnl)}`}>{formatPct(totalPnl / totalCost)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">持仓数量</div>
          <p className="text-xl font-bold">{positions.length} / 5</p>
        </div>
      </div>

      {/* Pending Orders */}
      {activeTab === "v5" && v5?.pending_orders && v5.pending_orders.length > 0 && (
        <div className="border rounded-lg bg-card p-4">
          <h2 className="font-semibold flex items-center gap-2 mb-3">
            <Clock className="h-4 w-4 text-yellow-500" />
            待执行挂单
          </h2>
          <div className="flex flex-wrap gap-2">
            {v5.pending_orders.map((o, i) => (
              <span key={i} className="px-3 py-1.5 text-xs border rounded-full bg-yellow-50 text-yellow-700">
                {o.code} {o.name || ""} {o.note || ""}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Positions */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold">当前持仓</h2>
        </div>
        {loading ? (
          <div className="p-8 text-center text-muted-foreground">加载中...</div>
        ) : positions.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">暂无持仓</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-right font-medium">买入价</th>
                  <th className="px-4 py-2 text-right font-medium">现价</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-right font-medium">成本</th>
                  <th className="px-4 py-2 text-right font-medium">市值</th>
                  <th className="px-4 py-2 text-right font-medium">盈亏</th>
                  {activeTab === "v1" && <th className="px-4 py-2 text-right font-medium">E价</th>}
                  {activeTab === "v1" && <th className="px-4 py-2 text-right font-medium">止损</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">评分</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">最高</th>}
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const mv = pos.current_price * pos.shares;
                  const pnl = mv - pos.cost;
                  const pnlPct = pnl / pos.cost;
                  return (
                    <tr key={pos.code} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-3 font-mono text-xs">{pos.code}</td>
                      <td className="px-4 py-3 font-medium">{pos.name}</td>
                      <td className="px-4 py-3 text-right">{pos.buy_price.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-medium">{pos.current_price.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right">{pos.shares}</td>
                      <td className="px-4 py-3 text-right text-muted-foreground">{formatMoney(pos.cost)}</td>
                      <td className="px-4 py-3 text-right">{formatMoney(mv)}</td>
                      <td className={`px-4 py-3 text-right font-medium ${pnlClass(pnlPct)}`}>
                        <div>{formatMoney(pnl)}</div>
                        <div className="text-xs">{formatPct(pnlPct)}</div>
                      </td>
                      {activeTab === "v1" && isV1(pos) && (
                        <>
                          <td className="px-4 py-3 text-right font-mono text-xs">
                            {pos.E.toFixed(2)}
                            {pos.current_price >= pos.E ? (
                              <span className="ml-1 text-green-600">✓</span>
                            ) : (
                              <span className="ml-1 text-red-600">✗</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs text-red-600">
                            {pos.stop.toFixed(2)}
                          </td>
                        </>
                      )}
                      {activeTab === "v5" && !isV1(pos) && (
                        <>
                          <td className="px-4 py-3 text-right">
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                              pos.score >= 72 ? "bg-green-100 text-green-700" :
                              pos.score >= 60 ? "bg-yellow-100 text-yellow-700" :
                              "bg-red-100 text-red-700"
                            }`}>
                              {pos.score}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                            {pos.highest?.toFixed(2) || "-"}
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trade History */}
      {state?.history && state.history.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <History className="h-4 w-4" />
            <h2 className="font-semibold">交易记录</h2>
            <span className="text-xs text-muted-foreground">（最近 {Math.min(state.history.length, 20)} 条）</span>
          </div>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">日期</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-left font-medium">操作</th>
                  <th className="px-4 py-2 text-right font-medium">价格</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-right font-medium">盈亏</th>
                  <th className="px-4 py-2 text-left font-medium">备注</th>
                </tr>
              </thead>
              <tbody>
                {state.history.slice(0, 30).map((t, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{t.date}</td>
                    <td className="px-4 py-2.5 font-mono text-xs">{t.code}</td>
                    <td className="px-4 py-2.5">{t.name || "-"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.action === "buy" ? "bg-green-100 text-green-700" :
                        t.action === "sell" ? "bg-red-100 text-red-700" :
                        "bg-yellow-100 text-yellow-700"
                      }`}>
                        {t.action === "buy" ? "买入" : t.action === "sell" ? "卖出" : t.action}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">{t.price?.toFixed(2) || "-"}</td>
                    <td className="px-4 py-2.5 text-right">{t.shares || "-"}</td>
                    <td className={`px-4 py-2.5 text-right font-medium ${t.pnl != null ? pnlClass(t.pnl > 0 ? 1 : -1) : "text-muted-foreground"}`}>
                      {t.pnl != null ? formatMoney(t.pnl) : "-"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{t.note || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

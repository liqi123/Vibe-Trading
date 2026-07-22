import { useEffect, useState } from "react";
import { Wallet, History, RefreshCw, Clock, TrendingDown, Save, Brain, Loader2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useModalStore } from "../stores/modal";

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

interface CVPick {
  rank: number;
  code: string;
  name: string;
  score: number;
  price: number;
  prev_close: number;
  change_pct: number;
}

interface CVPosition {
  code: string;
  name: string;
  buy_price: number;
  shares: number;
  cost: number;
  current_price: number;
  score: number;
}

interface ICTPosition {
  code: string;
  name: string;
  buy_price: number;
  shares: number;
  cost: number;
  current_price: number;
  highest: number;
  score: number;
  structure: number;
  sweep_level: number | null;
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
  const [cvSignal, setCvSignal] = useState<{picks: CVPick[]; count: number; threshold: number; median: number; date: string} | null>(null);
  const [cvPortfolio, setCvPortfolio] = useState<PaperState & {positions: CVPosition[]} | null>(null);
  const [ictPortfolio, setIctPortfolio] = useState<PaperState & {positions: ICTPosition[]} | null>(null);
  const [buyingCode, setBuyingCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"v1" | "v5" | "cv" | "ict" | "history" | "shadow">("v1");
  const [shadowLoading, setShadowLoading] = useState(false);
  const [shadowResult, setShadowResult] = useState<any>(null);
  const [shadowError, setShadowError] = useState<string | null>(null);
  const [shadowReportHtml, setShadowReportHtml] = useState<string | null>(null);
  const [sellingCode, setSellingCode] = useState<string | null>(null);
  const [editingE, setEditingE] = useState<Record<string, string>>({});
  const [savingE, setSavingE] = useState<string | null>(null);
  const openStock = useModalStore((s) => s.open);
  const [trades, setTrades] = useState<any[]>([]);

  const fetchData = async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      api.tools.get<any>("/portfolio"),
      api.tools.get<any>("/portfolio/v5"),
      api.tools.get<any>("/trades"),
      api.tools.get<any>("/trades/v5"),
      api.tools.get<any>("/composite-volume/portfolio"),
      api.tools.get<any>("/portfolio/ict"),
      api.tools.get<any>("/trades/ict"),
    ]);
    const ok = (i: number) => results[i].status === "fulfilled" ? (results[i] as PromiseFulfilledResult<any>).value : null;
    const r1 = ok(0), r5 = ok(1), t1 = ok(2), t5 = ok(3),
          cvPort = ok(4), ictPort = ok(5), tIct = ok(6);
    if (r1) setV1(r1);
    if (r5) setV5(r5);
    if (cvPort) setCvPortfolio(cvPort);
    if (ictPort) setIctPortfolio(ictPort);
    setTrades([
      ...(t1?.history || []).map((t: any) => ({ ...t, strategy: "V1" })),
      ...(t5?.history || []).map((t: any) => ({ ...t, strategy: "V5" })),
      ...(cvPort?.history || []).map((t: any) => ({ ...t, strategy: "CV" })),
      ...(tIct?.history || []).map((t: any) => ({ ...t, strategy: "ICT" })),
    ]);
    setLoading(false);
    // signal 单独加载，不阻塞页面
    api.tools.get<any>("/composite-volume/signal").then(r => { if (r?.ok) setCvSignal(r); }).catch(() => {});
  };

  useEffect(() => { fetchData(); }, []);

  const handleSaveE = async (code: string, portfolio: string) => {
    const val = parseFloat(editingE[code]);
    if (isNaN(val)) return;
    setSavingE(code);
    try {
      await api.tools.post<any>("/portfolio/update-field", { code, portfolio, field: "E", value: val });
      fetchData();
    } catch { /* ignore */ }
    setSavingE(null);
    setEditingE(prev => { const n = { ...prev }; delete n[code]; return n; });
  };

  const handleSell = async (code: string, portfolio: string) => {
    if (!confirm(`确认卖出 ${code}？`)) return;
    setSellingCode(code);
    try {
      const endpoint = portfolio === "cv" ? "/composite-volume/sell" : "/portfolio/sell";
      const result = await api.tools.post<any>(endpoint, {
        code, portfolio,
        reason: "手动卖出",
      });
      if (result.ok) {
        alert(`卖出成功，盈亏: ${formatMoney(result.pnl)}`);
        fetchData();
      } else {
        alert(`卖出失败: ${result.detail || "未知错误"}`);
      }
    } catch { alert("卖出请求失败"); }
    setSellingCode(null);
  };

  const handleCvBuy = async (pick: CVPick) => {
    if (!confirm(`确认买入 ${pick.name} (${pick.code}) ？`)) return;
    setBuyingCode(pick.code);
    try {
      const result = await api.tools.post<any>("/composite-volume/buy", {
        code: pick.code, name: pick.name,
        price: pick.price, score: pick.score,
      });
      if (result.ok) {
        alert(result.message);
        fetchData();
      } else {
        alert(`买入失败: ${result.detail}`);
      }
    } catch (e) {
      alert("买入请求失败");
    }
    setBuyingCode(null);
  };

  const handleShadowAnalyze = async () => {
    setShadowLoading(true);
    setShadowError(null);
    setShadowResult(null);
    setShadowReportHtml(null);
    try {
      const data = await api.tools.post<any>("/shadow/analyze");
      if (data.ok) {
        setShadowResult(data);
        const reportData = await api.tools.get<any>(`/shadow/report/${data.shadow_id}`);
        if (reportData.ok) {
          setShadowReportHtml(reportData.html);
        }
      } else {
        setShadowError(data.detail || "分析失败");
      }
    } catch (e) {
      setShadowError("请求失败: " + String(e));
    }
    setShadowLoading(false);
  };

  const state = activeTab === "v1" ? v1 : activeTab === "v5" ? v5 : activeTab === "cv" ? cvPortfolio : activeTab === "ict" ? ictPortfolio : null;
  const positions = state?.positions || [];
  const cash = state?.cash || 0;
  const initial = state?.initial_capital || 200000;

  const marketValue = positions.reduce((s, p: any) => s + (p.current_price || p.buy_price) * p.shares, 0);
  const totalCost = positions.reduce((s, p: any) => s + p.cost, 0);
  const totalPnl = marketValue - totalCost;
  const totalValue = cash + marketValue;
  const totalReturn = (totalValue - initial) / initial;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">模拟盘</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {activeTab === "history" ? "全部交易历史" : state?.name || (activeTab === "v1" ? "斐波那契策略" : activeTab === "cv" ? "复合量价策略" : activeTab === "ict" ? "ICT/SMC策略" : "趋势策略")}
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
        {(["v1", "v5", "cv", "ict", "history", "shadow"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "v1" ? "V1 斐波那契" : tab === "v5" ? "V5 趋势" : tab === "cv" ? "复合量价" : tab === "ict" ? "ICT/SMC" : tab === "shadow" ? "影子账户" : "交易历史"}
          </button>
        ))}
      </div>

      {/* Summary */}
      {activeTab !== "history" && activeTab !== "shadow" && <div className="grid gap-4 md:grid-cols-5">
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
      </div>}

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

      {/* CV: Today's Picks */}
      {activeTab === "cv" && cvSignal && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center justify-between">
            <h2 className="font-semibold flex items-center gap-2">
              今日精选 (Top 1%)
              <span className="text-xs text-muted-foreground font-normal">{cvSignal.date} · 共{cvSignal.count}只 · 门槛分{cvSignal.threshold.toFixed(4)}</span>
            </h2>
          </div>
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium w-8">#</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-right font-medium">价格</th>
                  <th className="px-4 py-2 text-right font-medium">涨幅</th>
                  <th className="px-4 py-2 text-right font-medium">因子分</th>
                  <th className="px-4 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {cvSignal.picks.map(pick => {
                  const held = cvPortfolio?.positions?.some(p => p.code === pick.code);
                  return (
                    <tr key={pick.code} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-2 text-muted-foreground">{pick.rank}</td>
                      <td className="px-4 py-2 font-mono text-xs cursor-pointer hover:text-primary"
                          onClick={() => openStock(pick.code)}>{pick.code}</td>
                      <td className="px-4 py-2 font-medium cursor-pointer hover:text-primary" onClick={() => openStock(pick.code)}>{pick.name}</td>
                      <td className="px-4 py-2 text-right font-mono">{pick.price.toFixed(2)}</td>
                      <td className={`px-4 py-2 text-right font-mono ${pick.change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {formatPct(pick.change_pct / 100)}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">{pick.score.toFixed(4)}</td>
                      <td className="px-4 py-2 text-center">
                        <button
                          onClick={() => handleCvBuy(pick)}
                          disabled={buyingCode === pick.code || held}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded transition-colors disabled:opacity-50 ${
                            held
                              ? "bg-gray-100 text-gray-400 border border-gray-200 cursor-not-allowed"
                              : "text-red-600 border border-red-200 hover:bg-red-50"
                          }`}
                        >
                          {held ? "已持仓" : buyingCode === pick.code ? "买入中..." : "买入"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Positions */}
      {activeTab !== "history" && activeTab !== "shadow" && <div className="border rounded-lg bg-card overflow-hidden">
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
                  <th className="px-4 py-2 text-right font-medium">成本价</th>
                  <th className="px-4 py-2 text-right font-medium">现价</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-right font-medium">成本</th>
                  <th className="px-4 py-2 text-right font-medium">市值</th>
                  <th className="px-4 py-2 text-right font-medium">盈亏</th>
                  {activeTab === "v1" && <th className="px-4 py-2 text-right font-medium">跑路价</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">评分</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">最高</th>}
                  {activeTab === "cv" && <th className="px-4 py-2 text-right font-medium">因子分</th>}
                  <th className="px-4 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const mv = pos.current_price * pos.shares;
                  const pnl = mv - pos.cost;
                  const pnlPct = pnl / pos.cost;
                  const unitCost = pos.shares > 0 ? pos.cost / pos.shares : pos.buy_price;
                  return (
                    <tr key={pos.code} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-3 font-mono text-xs cursor-pointer hover:text-primary" onClick={() => openStock(pos.code)}>{pos.code}</td>
                      <td className="px-4 py-3 font-medium cursor-pointer hover:text-primary" onClick={() => openStock(pos.code)}>{pos.name}</td>
                      <td className="px-4 py-3 text-right font-mono">{unitCost.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-medium">{pos.current_price.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right">{pos.shares}</td>
                      <td className="px-4 py-3 text-right text-muted-foreground">{formatMoney(pos.cost)}</td>
                      <td className="px-4 py-3 text-right">{formatMoney(mv)}</td>
                      <td className={`px-4 py-3 text-right font-medium ${pnlClass(pnlPct)}`}>
                        <div>{formatMoney(pnl)}</div>
                        <div className="text-xs">{formatPct(pnlPct)}</div>
                      </td>
                      {activeTab === "v1" && isV1(pos) && (
                        <td className="px-4 py-3 text-right">
                          {editingE[pos.code] !== undefined ? (
                            <div className="flex items-center gap-1 justify-end">
                              <input
                                type="number"
                                step="0.01"
                                value={editingE[pos.code]}
                                onChange={e => setEditingE(prev => ({ ...prev, [pos.code]: e.target.value }))}
                                className="w-20 px-1 py-0.5 text-right text-xs border rounded font-mono"
                                autoFocus
                              />
                              <button
                                onClick={() => handleSaveE(pos.code, activeTab)}
                                disabled={savingE === pos.code}
                                className="p-0.5 text-green-600 hover:text-green-700"
                              >
                                <Save className="h-3 w-3" />
                              </button>
                            </div>
                          ) : (
                            <div
                              className="flex items-center gap-1 justify-end cursor-pointer hover:bg-muted/50 rounded px-1"
                              onClick={() => setEditingE(prev => ({ ...prev, [pos.code]: pos.E.toFixed(2) }))}
                            >
                              <span className="font-mono text-xs">{pos.E.toFixed(2)}</span>
                              {pos.current_price >= pos.E ? (
                                <span className="text-green-600">✓</span>
                              ) : (
                                <span className="text-red-600">✗</span>
                              )}
                            </div>
                          )}
                        </td>
                      )}
                      {activeTab === "v5" && !isV1(pos) && (
                        <>
                          <td className="px-4 py-3 text-right">
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                              pos.score >= 72 ? "bg-green-100 text-green-700" :
                              pos.score >= 60 ? "bg-yellow-100 text-yellow-700" :
                              "bg-red-100 text-red-700"
                            }`}>
                              {pos.score.toFixed(1)}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                            {pos.highest?.toFixed(2) || "-"}
                          </td>
                        </>
                      )}
                      {activeTab === "cv" && (
                        <td className="px-4 py-3 text-right font-mono text-xs">
                          {(pos as any).score?.toFixed(4) || "-"}
                        </td>
                      )}
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleSell(pos.code, activeTab)}
                          disabled={sellingCode === pos.code}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors disabled:opacity-50"
                        >
                          <TrendingDown className="h-3 w-3" />
                          {sellingCode === pos.code ? "卖出中..." : "卖出"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>}

      {/* All Trade History (history tab) */}
      {activeTab === "history" && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <History className="h-4 w-4" />
            <h2 className="font-semibold">全部交易历史</h2>
            <span className="text-xs text-muted-foreground">（V1 + V5 + CV 合计 {trades.length} 条）</span>
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">日期</th>
                  <th className="px-4 py-2 text-left font-medium">策略</th>
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
                {trades.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">暂无交易记录</td></tr>
                ) : (
                  trades.map((t, i) => (
                    <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{t.date}</td>
                      <td className="px-4 py-2.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          t.strategy === "V1" ? "bg-blue-100 text-blue-700" :
                          t.strategy === "CV" ? "bg-orange-100 text-orange-700" :
                          "bg-purple-100 text-purple-700"
                        }`}>
                          {t.strategy}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs cursor-pointer hover:text-primary" onClick={() => openStock(t.code)}>{t.code}</td>
                      <td className="px-4 py-2.5 cursor-pointer hover:text-primary" onClick={() => openStock(t.code)}>{t.name || "-"}</td>
                      <td className="px-4 py-2.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          t.strategy === "V1" ? "bg-blue-100 text-blue-700" :
                          t.strategy === "CV" ? "bg-orange-100 text-orange-700" :
                          "bg-purple-100 text-purple-700"
                        }`}>
                          {t.strategy}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right">{t.price?.toFixed(2) || "-"}</td>
                      <td className="px-4 py-2.5 text-right">{t.shares || "-"}</td>
                      <td className={`px-4 py-2.5 text-right font-medium ${t.pnl != null ? pnlClass(t.pnl > 0 ? 1 : -1) : "text-muted-foreground"}`}>
                        {t.pnl != null ? formatMoney(t.pnl) : "-"}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{t.note || ""}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Shadow Account */}
      {activeTab === "shadow" && (
        <div className="space-y-4">
          <div className="border rounded-lg bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <Brain className="h-6 w-6 text-purple-500" />
                <div>
                  <h2 className="font-semibold text-lg">影子账户分析</h2>
                  <p className="text-sm text-muted-foreground">从模拟盘交易记录中提取交易规则，分析实际操作与规则的偏差</p>
                </div>
              </div>
              <button
                onClick={handleShadowAnalyze}
                disabled={shadowLoading}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-purple-600 rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
              >
                {shadowLoading ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> 分析中...</>
                ) : (
                  <>开始分析</>
                )}
              </button>
            </div>

            {shadowError && (
              <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {shadowError}
              </div>
            )}

            {shadowResult && !shadowReportHtml && (
              <div className="grid gap-4 md:grid-cols-4">
                <div className="border rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">盈利轮次</div>
                  <p className="text-xl font-bold">{shadowResult.profitable_roundtrips} / {shadowResult.total_roundtrips}</p>
                </div>
                <div className="border rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">提取规则</div>
                  <p className="text-xl font-bold">{shadowResult.rules?.length || 0} 条</p>
                </div>
                <div className="border rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">实盘盈亏</div>
                  <p className={`text-xl font-bold ${(shadowResult.real_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                    {(shadowResult.real_pnl || 0).toFixed(2)}
                  </p>
                </div>
                <div className="border rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">盈亏差值</div>
                  <p className={`text-xl font-bold ${(shadowResult.delta_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                    {(shadowResult.delta_pnl || 0).toFixed(2)}
                  </p>
                </div>
              </div>
            )}

            {shadowResult && (
              <div className="mt-4">
                <h3 className="font-medium mb-2">提取规则</h3>
                <div className="space-y-2">
                  {shadowResult.rules?.map((r: any) => (
                    <div key={r.rule_id} className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
                      <span className="px-2 py-0.5 text-xs font-mono bg-purple-100 text-purple-700 rounded">{r.rule_id}</span>
                      <span className="text-sm flex-1">{r.human_text}</span>
                      <span className="text-xs text-muted-foreground">支撑 {r.support_count} 笔</span>
                      <span className="text-xs text-muted-foreground">覆盖 {(r.coverage_rate * 100).toFixed(0)}%</span>
                      <span className="text-xs text-muted-foreground">持仓 {r.holding_days_range[0]}-{r.holding_days_range[1]}天</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {shadowReportHtml && (
            <div className="border rounded-lg bg-card overflow-hidden">
              <div className="px-4 py-3 border-b flex items-center justify-between">
                <h2 className="font-semibold">影子账户报告</h2>
                <a
                  href={shadowResult ? `/shadow-reports/${shadowResult.shadow_id}` : "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-primary hover:underline"
                >
                  在新窗口打开
                </a>
              </div>
              <iframe
                srcDoc={shadowReportHtml}
                className="w-full border-0"
                style={{ height: "80vh" }}
                title="Shadow Account Report"
              />
            </div>
          )}
        </div>
      )}

      {/* Trade History (per strategy) */}
      {activeTab !== "history" && activeTab !== "shadow" && state?.history && state.history.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <History className="h-4 w-4" />
            <h2 className="font-semibold">交易记录</h2>
            <span className="text-xs text-muted-foreground">（最近 {Math.min(state.history.length, 30)} 条）</span>
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
                    <td className="px-4 py-2.5 font-mono text-xs cursor-pointer hover:text-primary" onClick={() => openStock(t.code)}>{t.code}</td>
                    <td className="px-4 py-2.5 cursor-pointer hover:text-primary" onClick={() => openStock(t.code)}>{t.name || "-"}</td>
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

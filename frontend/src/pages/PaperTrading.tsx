import { useEffect, useState } from "react";
import { Wallet, History, RefreshCw, Clock, TrendingDown, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useModalStore } from "../stores/modal";
import { api } from "@/lib/api";

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
  strategy?: string;
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
  const [activeTab, setActiveTab] = useState<"v1" | "v5" | "history">("v1");
  const [sellingCode, setSellingCode] = useState<string | null>(null);
  const [editingE, setEditingE] = useState<Record<string, string>>({});
  const [savingE, setSavingE] = useState<string | null>(null);
  const openStock = useModalStore((s) => s.open);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const { t } = useTranslation();

  const fetchData = async () => {
    setLoading(true);
    try {
      const [v1Data, v5Data, t1Data, t5Data] = await Promise.all([
        api.tools.get<any>("/portfolio"),
        api.tools.get<any>("/portfolio/v5"),
        api.tools.get<any>("/trades"),
        api.tools.get<any>("/trades/v5"),
      ]);
      setV1(v1Data);
      setV5(v5Data);
      setTrades([
        ...(t1Data.history || []).map((t: TradeRecord) => ({ ...t, strategy: "V1" })),
        ...(t5Data.history || []).map((t: TradeRecord) => ({ ...t, strategy: "V5" })),
      ]);
    } catch (e) { console.error('Failed to fetch paper trading data:', e); }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  const handleSaveE = async (code: string, portfolio: string) => {
    const val = parseFloat(editingE[code]);
    if (isNaN(val)) return;
    setSavingE(code);
    try {
      await api.tools.post<any>("/portfolio/update-field", { code, portfolio, field: "E", value: val });
      fetchData();
    } catch (e) { console.error('Failed to save E price:', e); }
    setSavingE(null);
    setEditingE(prev => { const n = { ...prev }; delete n[code]; return n; });
  };

  const handleSell = async (code: string, portfolio: string) => {
    if (!confirm(t("paperTrading.confirmSell", { code }))) return;
    setSellingCode(code);
    try {
      const result = await api.tools.post<any>("/portfolio/sell", { code, portfolio, reason: "手动卖出" });
      if (result.ok) {
        console.log(`卖出成功，盈亏: ${formatMoney(result.pnl)}`);
        fetchData();
      } else {
        console.log(`卖出失败: ${result.detail || "未知错误"}`);
      }
    } catch (e) {
      console.log("卖出请求失败");
    }
    setSellingCode(null);
  };

  const state = activeTab === "v1" ? v1 : activeTab === "v5" ? v5 : null;
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
          <h1 className="text-2xl font-bold">{t("paperTrading.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {activeTab === "history" ? t("paperTrading.allTradeHistory") : state?.name || (activeTab === "v1" ? t("paperTrading.fibStrategy") : t("paperTrading.trendStrategy"))}
          </p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
           {t("paperTrading.refresh")}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b">
        {(["v1", "v5", "history"] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab === "v1" ? t("paperTrading.tabV1") : tab === "v5" ? t("paperTrading.tabV5") : t("paperTrading.tabHistory")}
          </button>
        ))}
      </div>

      {/* Summary */}
      {activeTab !== "history" && <div className="grid gap-4 md:grid-cols-5">
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
             <Wallet className="h-4 w-4" />
             {t("paperTrading.totalAssets")}
          </div>
          <p className="text-xl font-bold">{formatMoney(totalValue)}</p>
          <p className={`text-xs ${pnlClass(totalReturn)}`}>{formatPct(totalReturn)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("paperTrading.availableCash")}</div>
          <p className="text-xl font-bold">{formatMoney(cash)}</p>
          <p className="text-xs text-muted-foreground">{t("paperTrading.ratio")} {(cash / totalValue * 100).toFixed(1)}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("paperTrading.marketValue")}</div>
          <p className="text-xl font-bold">{formatMoney(marketValue)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("paperTrading.positionPnl")}</div>
          <p className={`text-xl font-bold ${pnlClass(totalPnl)}`}>{formatMoney(totalPnl)}</p>
          <p className={`text-xs ${pnlClass(totalPnl)}`}>{formatPct(totalPnl / totalCost)}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("paperTrading.positionCount")}</div>
          <p className="text-xl font-bold">{positions.length} / 5</p>
        </div>
      </div>}

      {/* Pending Orders */}
      {activeTab === "v5" && v5?.pending_orders && v5.pending_orders.length > 0 && (
        <div className="border rounded-lg bg-card p-4">
          <h2 className="font-semibold flex items-center gap-2 mb-3">
             <Clock className="h-4 w-4 text-yellow-500" />
             {t("paperTrading.pendingOrders")}
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
      {activeTab !== "history" && <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold">{t("paperTrading.currentPositions")}</h2>
        </div>
        {loading ? (
          <div className="p-8 text-center text-muted-foreground">{t("paperTrading.loading")}</div>
        ) : positions.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">{t("paperTrading.noPositions")}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thCode")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thName")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thCostPrice")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thCurrentPrice")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thShares")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thCost")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thMarketValue")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thPnl")}</th>
                  {activeTab === "v1" && <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thEscapePrice")}</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thScore")}</th>}
                  {activeTab === "v5" && <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thHighest")}</th>}
                  <th className="px-4 py-2 text-center font-medium">{t("paperTrading.thAction")}</th>
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
                      <td className="px-4 py-3 font-medium">{pos.name}</td>
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
                              {pos.score}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                            {pos.highest?.toFixed(2) || "-"}
                          </td>
                        </>
                      )}
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleSell(pos.code, activeTab)}
                          disabled={sellingCode === pos.code}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors disabled:opacity-50"
                        >
                          <TrendingDown className="h-3 w-3" />
                          {sellingCode === pos.code ? t("paperTrading.selling") : t("paperTrading.sell")}
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
            <h2 className="font-semibold">{t("paperTrading.allTradeHistory")}</h2>
            <span className="text-xs text-muted-foreground">{t("paperTrading.tradeCountTotal", { count: trades.length })}</span>
          </div>
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thDate")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thStrategy")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thCode")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thName")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thAction")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thPrice")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thShares")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thPnl")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thNote")}</th>
                </tr>
              </thead>
              <tbody>
                  {trades.length === 0 ? (
                    <tr><td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">{t("paperTrading.noTrades")}</td></tr>
                ) : (
                  trades.map((tr, i) => (
                    <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{tr.date}</td>
                      <td className="px-4 py-2.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${tr.strategy === "V1" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>
                          {tr.strategy}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs cursor-pointer hover:text-primary" onClick={() => openStock(tr.code)}>{tr.code}</td>
                      <td className="px-4 py-2.5">{tr.name || "-"}</td>
                      <td className="px-4 py-2.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          tr.action === "buy" ? "bg-green-100 text-green-700" :
                          tr.action === "sell" ? "bg-red-100 text-red-700" :
                          "bg-yellow-100 text-yellow-700"
                        }`}>
                          {tr.action === "buy" ? t("paperTrading.buyAction") : tr.action === "sell" ? t("paperTrading.sellAction") : tr.action}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right">{tr.price?.toFixed(2) || "-"}</td>
                      <td className="px-4 py-2.5 text-right">{tr.shares || "-"}</td>
                      <td className={`px-4 py-2.5 text-right font-medium ${tr.pnl != null ? pnlClass(tr.pnl > 0 ? 1 : -1) : "text-muted-foreground"}`}>
                        {tr.pnl != null ? formatMoney(tr.pnl) : "-"}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{tr.note || ""}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trade History (per strategy) */}
      {activeTab !== "history" && state?.history && state.history.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center gap-2">
            <History className="h-4 w-4" />
            <h2 className="font-semibold">{t("paperTrading.tradeHistory")}</h2>
            <span className="text-xs text-muted-foreground">{t("paperTrading.recentCount", { count: Math.min(state.history.length, 30) })}</span>
          </div>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thDate")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thCode")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thName")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thAction")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thPrice")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thShares")}</th>
                  <th className="px-4 py-2 text-right font-medium">{t("paperTrading.thPnl")}</th>
                  <th className="px-4 py-2 text-left font-medium">{t("paperTrading.thNote")}</th>
                </tr>
              </thead>
              <tbody>
                {state.history.slice(0, 30).map((tr, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{tr.date}</td>
                    <td className="px-4 py-2.5 font-mono text-xs cursor-pointer hover:text-primary" onClick={() => openStock(tr.code)}>{tr.code}</td>
                    <td className="px-4 py-2.5">{tr.name || "-"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        tr.action === "buy" ? "bg-green-100 text-green-700" :
                        tr.action === "sell" ? "bg-red-100 text-red-700" :
                        "bg-yellow-100 text-yellow-700"
                      }`}>
                        {tr.action === "buy" ? t("paperTrading.buyAction") : tr.action === "sell" ? t("paperTrading.sellAction") : tr.action}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">{tr.price?.toFixed(2) || "-"}</td>
                    <td className="px-4 py-2.5 text-right">{tr.shares || "-"}</td>
                    <td className={`px-4 py-2.5 text-right font-medium ${tr.pnl != null ? pnlClass(tr.pnl > 0 ? 1 : -1) : "text-muted-foreground"}`}>
                      {tr.pnl != null ? formatMoney(tr.pnl) : "-"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{tr.note || ""}</td>
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

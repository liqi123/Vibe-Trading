import { useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2, Edit2, Check, X, CandlestickChart as CandleIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useModalStore } from "../stores/modal";
import { api } from "@/lib/api";
import { SMCChart } from "@/components/charts/SMCChart";

interface WatchlistItem {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  e_price: number;
  x_price: number;
  runaway_price: number;
}



  const getSuggestionKey = (price: number, e: number, x: number, run: number): { textKey: string; color: string } => {
    if (!price || !e) return { textKey: "suggestionNone", color: "text-muted-foreground" };
    if (price < e) return { textKey: "suggestionBuy", color: "text-green-600 font-bold" };
    if (x && price >= x && (!run || price < run)) return { textKey: "suggestionConsiderSell", color: "text-orange-600 font-bold" };
    if (run && price >= run) return { textKey: "suggestionSell", color: "text-red-600 font-bold" };
    return { textKey: "suggestionHold", color: "text-blue-600" };
  };

interface PositionData {
  code: string;
  name?: string;
  e_price?: number;
  x_price?: number;
  runaway_price?: number;
}

export function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [searchResults, setSearchResults] = useState<{code: string; name: string}[]>([]);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [editValues, setEditValues] = useState({ e_price: "", x_price: "", runaway_price: "" });
  const openStock = useModalStore((s) => s.open);
  const { t } = useTranslation();
  const [smcStock, setSmcStock] = useState<{ code: string; name: string } | null>(null);
  const [smcData, setSmcData] = useState<any>(null);
  const [smcLoading, setSmcLoading] = useState(false);

  const openSMC = async (code: string, name: string) => {
    setSmcStock({ code, name });
    setSmcData(null);
    setSmcLoading(true);
    try {
      const r = await api.tools.get<any>(`/smc/${code}`);
      if (r?.ok) setSmcData(r);
    } catch {}
    setSmcLoading(false);
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>("/expectations");
      const positions = data.positions || [];
      if (positions.length > 0) {
        const codes = positions.map((p: PositionData) => p.code).join(",");
        const priceData = await api.tools.get<any>(`/prices?codes=${codes}`);
        const enriched = positions.map((p: PositionData) => {
          const priceInfo = priceData.prices?.[p.code]
            || priceData.prices?.[p.code.startsWith("6") ? "sh" + p.code : "sz" + p.code]
            || {};
          return {
            code: p.code,
            name: p.name || priceInfo.name || "",
            price: priceInfo.price || 0,
            change_pct: priceInfo.change_pct || 0,
            e_price: p.e_price || 0,
            x_price: p.x_price || 0,
            runaway_price: p.runaway_price || 0,
          };
        });
        setItems(enriched);
      } else {
        setItems([]);
      }
    } catch (e) {
    } finally {
      setLoading(false);
    }
  };

  const searchStock = async (q: string) => {
    if (!q.trim()) { setSearchResults([]); return; }
    try {
      const data = await api.tools.get<any>(`/expectations/search?q=${encodeURIComponent(q.trim())}`);
      setSearchResults(data.results || []);
    } catch (e) { /* ignore */ }
  };

  const addStock = async (code?: string) => {
    const input = code || newCode.trim();
    if (!input) return;
    try {
      await api.tools.post<any>("/expectations/add", { code: input });
      setNewCode("");
      setSearchResults([]);
      setShowAddModal(false);
      fetchData();
    } catch (e) { /* ignore */ }
  };

  const removeStock = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/remove", { code });
      fetchData();
    } catch (e) { /* ignore */ }
  };

  const startEdit = (item: WatchlistItem) => {
    setEditingCode(item.code);
    setEditValues({
      e_price: item.e_price ? String(item.e_price) : "",
      x_price: item.x_price ? String(item.x_price) : "",
      runaway_price: item.runaway_price ? String(item.runaway_price) : "",
    });
  };

  const cancelEdit = () => {
    setEditingCode(null);
    setEditValues({ e_price: "", x_price: "", runaway_price: "" });
  };

  const saveEdit = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/update-prices", {
        code,
        e_price: parseFloat(editValues.e_price) || 0,
        x_price: parseFloat(editValues.x_price) || 0,
        runaway_price: parseFloat(editValues.runaway_price) || 0,
      });
      setEditingCode(null);
      fetchData();
    } catch (e) { /* ignore */ }
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
          <h1 className="text-2xl font-bold">{t("watchlist.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("watchlist.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t("watchlist.add")}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("watchlist.refresh")}
          </button>
        </div>
      </div>

      <div className="border rounded-lg bg-card overflow-hidden">
        {items.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            {t("watchlist.emptyHint")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">{t("watchlist.thCode")}</th>
                  <th className="px-4 py-3 text-left font-medium">{t("watchlist.thName")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("watchlist.thPrice")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("watchlist.thChange")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("watchlist.thEPrice")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("watchlist.thXPrice")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("watchlist.thRunawayPrice")}</th>
                  <th className="px-4 py-3 text-center font-medium">{t("watchlist.thSuggestion")}</th>
                  <th className="px-4 py-3 text-center font-medium">{t("watchlist.thAction")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isEditing = editingCode === item.code;
                  const sug = getSuggestionKey(item.price, item.e_price, item.x_price, item.runaway_price);
                  return (
                    <tr key={item.code} className="border-t hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3 font-mono cursor-pointer hover:text-primary" onClick={() => openStock(item.code)}>{item.code}</td>
                      <td className="px-4 py-3">{item.name}</td>
                      <td className={`px-4 py-3 text-right font-medium ${item.change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {item.price.toFixed(2)}
                      </td>
                      <td className={`px-4 py-3 text-right ${item.change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {item.change_pct >= 0 ? "+" : ""}{item.change_pct.toFixed(2)}%
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input
                            type="number"
                            step="0.01"
                            value={editValues.e_price}
                            onChange={(e) => setEditValues({ ...editValues, e_price: e.target.value })}
                            className="w-20 px-2 py-1 text-right text-sm border rounded bg-background"
                          />
                        ) : (
                          <span className="font-mono text-primary">{item.e_price ? item.e_price.toFixed(2) : "-"}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input
                            type="number"
                            step="0.01"
                            value={editValues.x_price}
                            onChange={(e) => setEditValues({ ...editValues, x_price: e.target.value })}
                            className="w-20 px-2 py-1 text-right text-sm border rounded bg-background"
                          />
                        ) : (
                          <span className="font-mono text-green-600">{item.x_price ? item.x_price.toFixed(2) : "-"}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input
                            type="number"
                            step="0.01"
                            value={editValues.runaway_price}
                            onChange={(e) => setEditValues({ ...editValues, runaway_price: e.target.value })}
                            className="w-20 px-2 py-1 text-right text-sm border rounded bg-background"
                          />
                        ) : (
                          <span className="font-mono text-orange-600">{item.runaway_price ? item.runaway_price.toFixed(2) : "-"}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className={`text-xs ${sug.color}`}>
                          {sug.textKey === "suggestionNone" ? t("watchlist.suggestionNone") :
                           sug.textKey === "suggestionBuy" ? t("watchlist.suggestionBuy") :
                           sug.textKey === "suggestionConsiderSell" ? t("watchlist.suggestionConsiderSell") :
                           sug.textKey === "suggestionSell" ? t("watchlist.suggestionSell") :
                           t("watchlist.suggestionHold")}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isEditing ? (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => saveEdit(item.code)}
                              className="p-1 text-green-600 hover:bg-green-100 rounded transition-colors"
                              title={t("watchlist.save")}
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              onClick={cancelEdit}
                              className="p-1 text-muted-foreground hover:bg-muted rounded transition-colors"
                              title={t("watchlist.cancel")}
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => openSMC(item.code, item.name)}
                              className="p-1 text-muted-foreground hover:text-purple-600 rounded transition-colors"
                              title="SMC结构图"
                            >
                              <CandleIcon className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => startEdit(item)}
                              className="p-1 text-muted-foreground hover:text-blue-600 rounded transition-colors"
                              title={t("watchlist.edit")}
                            >
                              <Edit2 className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => removeStock(item.code)}
                              className="p-1 text-muted-foreground hover:text-red-600 rounded transition-colors"
                              title={t("watchlist.delete")}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 添加自选股弹窗 */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowAddModal(false)}>
          <div className="bg-card rounded-lg p-6 w-96 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">{t("watchlist.addStockTitle")}</h3>
            <input
              autoFocus
              value={newCode}
              onChange={(e) => { setNewCode(e.target.value); searchStock(e.target.value); }}
              onKeyDown={(e) => { if (e.key === "Enter") addStock(); if (e.key === "Escape") setShowAddModal(false); }}
              placeholder={t("watchlist.searchPlaceholder")}
              className="w-full border rounded-md px-3 py-2 text-sm"
            />
            {searchResults.length > 0 && (
              <div className="mt-2 border rounded-md max-h-48 overflow-y-auto">
                {searchResults.map((r) => (
                  <button
                    key={r.code}
                    onClick={() => addStock(r.code)}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted flex justify-between items-center"
                  >
                    <span className="font-mono text-muted-foreground">{r.code}</span>
                    <span>{r.name}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm border rounded-md hover:bg-muted"
              >
                {t("watchlist.cancel")}
              </button>
              <button
                onClick={() => addStock()}
                className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90"
              >
                {t("watchlist.add")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SMC结构图弹窗 */}
      {smcStock && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div className="px-6 py-4 border-b flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">{smcStock.name} ({smcStock.code})</h3>
                <p className="text-sm text-muted-foreground">SMC结构图</p>
              </div>
              <button onClick={() => setSmcStock(null)} className="p-1 hover:bg-muted rounded">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-4">
              {/* 图例 */}
              <div className="flex flex-wrap gap-3 mb-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="inline-block w-0 h-0 border-l-4 border-r-4 border-b-6 border-l-transparent border-r-transparent border-b-green-500" />BOS多(结构突破)</span>
                <span className="flex items-center gap-1"><span className="inline-block w-0 h-0 border-l-4 border-r-4 border-t-6 border-l-transparent border-r-transparent border-t-red-500" />BOS空</span>
                <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rotate-45 bg-blue-500" />流动性扫盘</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-blue-500/20 border border-blue-500" />FVG(公允缺口)</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-purple-500/20 border border-purple-500 border-dashed" />OB(订单块)</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-amber-500/20 border border-amber-500 border-dotted" />OTE(最优入场区)</span>
              </div>
              {smcLoading ? (
                <div className="h-96 flex items-center justify-center text-muted-foreground">加载中...</div>
              ) : smcData?.klines ? (
                <SMCChart
                  klines={smcData.klines}
                  signals={smcData.signals || []}
                  sweeps={smcData.sweeps || []}
                  fvg_zones={smcData.fvg_zones || []}
                  ob_zones={smcData.ob_zones || []}
                  ote_zones={smcData.ote_zones || []}
                  height={400}
                />
              ) : (
                <div className="h-96 flex items-center justify-center text-muted-foreground">暂无图表数据</div>
              )}
              {/* 分析建议 */}
              {smcData?.analysis && (
                <div className="mt-3 p-3 bg-muted/30 rounded-lg text-sm">
                  <div className="flex items-center gap-4 mb-2 text-xs text-muted-foreground flex-wrap">
                    <span>日期: {smcData.analysis.date}</span>
                    <span>价格: {smcData.analysis.price}</span>
                    <span>趋势: {smcData.analysis.trend > 0 ? "上升" : smcData.analysis.trend < 0 ? "下降" : "震荡"}</span>
                    <span>MA20: {smcData.analysis.ma20}</span>
                    <span>MA60: {smcData.analysis.ma60}</span>
                    <span>RSI: {smcData.analysis.rsi}</span>
                  </div>
                  <div className="space-y-1 mb-2">
                    {smcData.analysis.points?.map((p: string, i: number) => (
                      <div key={i} className="flex items-start gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-primary mt-1.5 shrink-0" />
                        <span>{p}</span>
                      </div>
                    ))}
                  </div>
                  <div className="font-medium text-primary">
                    建议: {smcData.analysis.suggestion}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

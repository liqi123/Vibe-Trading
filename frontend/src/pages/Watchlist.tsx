import { useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2, Edit2, Check, X, CandlestickChart as CandleIcon, Network as NetworkIcon, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useModalStore } from "../stores/modal";
import { api } from "@/lib/api";
import { SMCChart } from "@/components/charts/SMCChart";
import { CzscChart, type CzscBuyPoint, type CzscBi, type CzscZS, type CzscKline } from "@/components/charts/CzscChart";

interface WatchlistItem {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  cost_price?: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  support?: number;
  resistance?: number;
  note?: string;
  category?: string;
  // 观察股专用：竞价 + 同花顺行业
  auction_price?: number;
  prev_close?: number;
  today_vol?: number;
  prev_vol?: number;
  industry?: string;
  concepts?: string[];
  auction_change_pct?: number;
  auction_vol_ratio?: number | null;
}





interface PositionData {
  code: string;
  name?: string;
  cost_price?: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  support?: number;
  resistance?: number;
  note?: string;
  category?: string;
}

export function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [searchResults, setSearchResults] = useState<{code: string; name: string}[]>([]);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [editValues, setEditValues] = useState({ cost_price: "" });
  const [editingNoteCode, setEditingNoteCode] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
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

  // 缠论弹窗状态
  const [czscStock, setCzscStock] = useState<{ code: string; name: string } | null>(null);
  const [czscData, setCzscData] = useState<any>(null);
  const [czscLoading, setCzscLoading] = useState(false);
  const [addCategory, setAddCategory] = useState<"observation" | "holding">("observation");

  const openCzsc = async (code: string, name: string) => {
    setCzscStock({ code, name });
    setCzscData(null);
    setCzscLoading(true);
    try {
      const r = await api.tools.get<any>(`/czsc/${code}?with_signals=true&limit=300`);
      if (r?.ok) setCzscData(r);
    } catch {}
    setCzscLoading(false);
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>("/expectations");
      const positions = data.positions || [];
      if (positions.length > 0) {
        const codes = positions.map((p: PositionData) => p.code).join(",");
        const priceData = await api.tools.get<any>(`/prices?codes=${codes}`);
        let enriched: WatchlistItem[] = positions.map((p: PositionData) => {
          const priceInfo = priceData.prices?.[p.code]
            || priceData.prices?.[p.code.startsWith("6") ? "sh" + p.code : "sz" + p.code]
            || {};
          return {
            code: p.code,
            name: p.name || priceInfo.name || "",
            price: priceInfo.price || 0,
            change_pct: priceInfo.change_pct || 0,
            cost_price: p.cost_price || 0,
            ma5: p.ma5,
            ma10: p.ma10,
            ma20: p.ma20,
            support: p.support,
            resistance: p.resistance,
            note: p.note || "",
            category: p.category || "holding",
          };
        });
        // 观察股：补充竞价数据 + 同花顺行业
        const obsCodes = enriched.filter((i) => i.category === "observation").map((i) => i.code);
        if (obsCodes.length > 0) {
          try {
            const aData = await api.tools.get<any>(`/watchlist-auction?codes=${obsCodes.join(",")}`);
            const a = aData.auction || {};
            enriched = enriched.map((it: WatchlistItem) => {
              if (it.category !== "observation") return it;
              const av = a[it.code] || {};
              const auctionPrice = av.auction_price || 0;
              const prevClose = av.prev_close || 0;
              const todayVol = Math.round(av.today_vol || 0);
              const prevVol = Math.round(av.prev_vol || 0);
              const chg = auctionPrice > 0 && prevClose > 0
                ? (auctionPrice - prevClose) / prevClose * 100
                : 0;
              const ratio = prevVol > 0 ? todayVol / prevVol : null;
              return {
                ...it,
                auction_price: auctionPrice,
                prev_close: prevClose,
                today_vol: todayVol,
                prev_vol: prevVol,
                industry: av.industry || "",
                concepts: av.concepts || [],
                auction_change_pct: chg,
                auction_vol_ratio: ratio,
              };
            });
          } catch (e) { /* ignore */ }
        }
        setItems(enriched);
      } else {
        setItems([]);
      }
    } catch (e) {
    } finally {
      setLoading(false);
    }
  };

  const updateSR = async (code: string) => {
    try {
      const r = await api.tools.post<any>("/expectations/update-support-resistance", { code });
      if (r?.ok) fetchData();
    } catch (e) { /* ignore */ }
  };

  const updateSRAll = async () => {
    const codes = items.map((it) => it.code);
    for (const c of codes) {
      try {
        await api.tools.post<any>("/expectations/update-support-resistance", { code: c });
      } catch (e) { /* ignore */ }
    }
    fetchData();
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
      await api.tools.post<any>("/expectations/add", { code: input, category: addCategory });
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
      cost_price: item.cost_price ? String(item.cost_price) : "",
    });
  };

  const cancelEdit = () => {
    setEditingCode(null);
    setEditValues({ cost_price: "" });
  };

  const saveEdit = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/update-prices", {
        code,
        cost_price: parseFloat(editValues.cost_price) || 0,
      });
      setEditingCode(null);
      fetchData();
    } catch (e) { /* ignore */ }
  };

  const startEditNote = (item: WatchlistItem) => {
    setEditingNoteCode(item.code);
    setEditNote(item.note || "");
  };

  const cancelEditNote = () => {
    setEditingNoteCode(null);
    setEditNote("");
  };

  const saveNote = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/update-prices", {
        code,
        note: editNote.trim(),
      });
      setEditingNoteCode(null);
      fetchData();
    } catch (e) { /* ignore */ }
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 10000);
    return () => clearInterval(timer);
  }, []);

  const observationItems = items.filter((i) => i.category === "observation");
  const holdingItems = items.filter((i) => i.category !== "observation");

  const handleAdd = (category: "observation" | "holding") => {
    setAddCategory(category);
    setNewCode("");
    setSearchResults([]);
    setShowAddModal(true);
  };

  const renderStockTable = (title: string, category: "observation" | "holding", rows: WatchlistItem[]) => (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <span className="text-xs text-muted-foreground">({rows.length})</span>
        </div>
        <button
          onClick={() => handleAdd(category)}
          className="flex items-center gap-1.5 px-2.5 py-1 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          {t("watchlist.add")}
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          {category === "observation" ? t("watchlist.observationEmpty") : t("watchlist.holdingEmpty")}
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
                <th className="px-4 py-3 text-right font-medium">成本价</th>
                <th className="px-4 py-3 text-right font-medium">盈亏</th>
                <th className="px-4 py-3 text-right font-medium">MA5</th>
                <th className="px-4 py-3 text-right font-medium">MA10</th>
                <th className="px-4 py-3 text-right font-medium">MA20</th>
                <th className="px-4 py-3 text-left font-medium">备注</th>
                <th className="px-4 py-3 text-center font-medium">{t("watchlist.thAction")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const isEditing = editingCode === item.code;
                const pnlPct = item.cost_price && item.cost_price > 0 && item.price > 0
                  ? ((item.price - item.cost_price) / item.cost_price * 100)
                  : null;
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
                          value={editValues.cost_price}
                          onChange={(e) => setEditValues({ ...editValues, cost_price: e.target.value })}
                          className="w-20 px-2 py-1 text-right text-sm border rounded bg-background"
                        />
                      ) : (
                        <span className="font-mono">{item.cost_price ? item.cost_price.toFixed(2) : "-"}</span>
                      )}
                    </td>
                    <td className={`px-4 py-3 text-right font-medium ${pnlPct == null ? "text-muted-foreground" : pnlPct >= 0 ? "text-red-600" : "text-green-600"}`}>
                      {pnlPct != null ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%` : "-"}
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground">{item.ma5?.toFixed(2) ?? "-"}</td>
                    <td className="px-4 py-3 text-right text-muted-foreground">{item.ma10?.toFixed(2) ?? "-"}</td>
                    <td className="px-4 py-3 text-right text-muted-foreground">{item.ma20?.toFixed(2) ?? "-"}</td>
                    <td className="px-4 py-3 text-left">
                      {editingNoteCode === item.code ? (
                        <input
                          autoFocus
                          type="text"
                          value={editNote}
                          onChange={(e) => setEditNote(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveNote(item.code);
                            if (e.key === "Escape") cancelEditNote();
                          }}
                          onBlur={() => saveNote(item.code)}
                          className="w-48 px-2 py-1 text-sm border rounded bg-background"
                          placeholder="输入备注"
                        />
                      ) : (
                        <span
                          className={`cursor-pointer ${item.note ? "" : "text-muted-foreground"}`}
                          onClick={() => startEditNote(item)}
                          title="点击编辑备注"
                        >
                          {item.note || "添加备注"}
                        </span>
                      )}
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
                            onClick={() => openCzsc(item.code, item.name)}
                            className="p-1 text-muted-foreground hover:text-indigo-600 rounded transition-colors"
                            title="缠论结构图（笔/中枢/买卖点）"
                          >
                            <NetworkIcon className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => updateSR(item.code)}
                            className="p-1 text-muted-foreground hover:text-purple-600 rounded transition-colors"
                            title="计算支撑/压力位写入备注"
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
  );

  const renderObservationTable = (title: string, rows: WatchlistItem[]) => (
    <div className="border rounded-lg bg-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <span className="text-xs text-muted-foreground">({rows.length})</span>
        </div>
        <button
          onClick={() => handleAdd("observation")}
          className="flex items-center gap-1.5 px-2.5 py-1 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          {t("watchlist.add")}
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          {t("watchlist.observationEmpty")}
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
                <th className="px-4 py-3 text-right font-medium">{t("watchlist.thAuctionChange")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("watchlist.thAuctionVol")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("watchlist.thAuctionRatio")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("watchlist.thIndustry")}</th>
                <th className="px-4 py-3 text-left font-medium">{t("watchlist.thConcept")}</th>
                <th className="px-4 py-3 text-left font-medium">备注</th>
                <th className="px-4 py-3 text-center font-medium">{t("watchlist.thAction")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const aucChg = item.auction_change_pct || 0;
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
                    <td className={`px-4 py-3 text-right font-medium ${aucChg >= 0 ? "text-red-600" : "text-green-600"}`}>
                      {item.auction_change_pct ? (aucChg >= 0 ? "+" : "") + aucChg.toFixed(2) + "%" : "-"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {item.today_vol ? item.today_vol.toLocaleString() : "-"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {item.auction_vol_ratio != null ? item.auction_vol_ratio.toFixed(2) : "-"}
                    </td>
                    <td className="px-4 py-3">{item.industry || "-"}</td>
                    <td className="px-4 py-3 max-w-[280px]">
                      {item.concepts && item.concepts.length > 0 ? (
                        <span
                          className="text-xs text-foreground/80 leading-relaxed"
                          title={item.concepts.join("、")}
                        >
                          {item.concepts.slice(0, 4).join("、")}
                          {item.concepts.length > 4 ? ` +${item.concepts.length - 4}` : ""}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-4 py-3 text-left">
                      {editingNoteCode === item.code ? (
                        <input
                          autoFocus
                          type="text"
                          value={editNote}
                          onChange={(e) => setEditNote(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveNote(item.code);
                            if (e.key === "Escape") cancelEditNote();
                          }}
                          onBlur={() => saveNote(item.code)}
                          className="w-48 px-2 py-1 text-sm border rounded bg-background"
                          placeholder="输入备注"
                        />
                      ) : (
                        <span
                          className={`cursor-pointer ${item.note ? "" : "text-muted-foreground"}`}
                          onClick={() => startEditNote(item)}
                          title="点击编辑备注"
                        >
                          {item.note || "添加备注"}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          onClick={() => openSMC(item.code, item.name)}
                          className="p-1 text-muted-foreground hover:text-purple-600 rounded transition-colors"
                          title="SMC结构图"
                        >
                          <CandleIcon className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => openCzsc(item.code, item.name)}
                          className="p-1 text-muted-foreground hover:text-indigo-600 rounded transition-colors"
                          title="缠论结构图（笔/中枢/买卖点）"
                        >
                          <NetworkIcon className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => removeStock(item.code)}
                          className="p-1 text-muted-foreground hover:text-red-600 rounded transition-colors"
                          title={t("watchlist.delete")}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("watchlist.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("watchlist.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("watchlist.refresh")}
          </button>
          <button
            onClick={updateSRAll}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors"
          >
            <CandleIcon className="h-4 w-4" />
            更新支撑/压力
          </button>
        </div>
      </div>

      {renderObservationTable(t("watchlist.observationTitle"), observationItems)}
      {renderStockTable(t("watchlist.holdingTitle"), "holding", holdingItems)}

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

      {/* 缠论结构图弹窗 */}
      {czscStock && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setCzscStock(null)}>
          <div className="bg-card rounded-lg shadow-xl max-w-5xl w-full max-h-[90vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b flex items-center justify-between flex-wrap gap-2">
              <div>
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <NetworkIcon className="h-4 w-4 text-indigo-500" />
                  {czscStock.name} ({czscStock.code})
                </h3>
                <p className="text-sm text-muted-foreground">缠论结构分析 · 笔 / 中枢 / 买卖点</p>
              </div>
              <button onClick={() => setCzscStock(null)} className="p-1 hover:bg-muted rounded">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-4 space-y-4 overflow-y-auto" style={{ maxHeight: "calc(90vh - 72px)" }}>
              {/* 图例 */}
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="inline-block w-5 h-0.5 bg-green-600" />向上笔</span>
                <span className="flex items-center gap-1"><span className="inline-block w-5 h-0.5 bg-red-600" />向下笔</span>
                <span className="flex items-center gap-1"><span className="inline-block w-5 h-3 bg-indigo-500/20 border border-indigo-500 border-dashed" />中枢</span>
                <span className="flex items-center gap-1"><span className="inline-block w-0 h-0 border-l-4 border-r-4 border-b-6 border-l-transparent border-r-transparent border-b-green-600" />买点</span>
              </div>

              {/* 评分 + 买点标签 */}
              {czscData && (
                <div className="flex items-center gap-4 flex-wrap">
                  {typeof czscData.score === "number" && (
                    <div className="flex items-baseline gap-1 px-3 py-1.5 rounded-lg border bg-indigo-500/10">
                      <span className="text-xs text-muted-foreground">缠论评分</span>
                      <span className="text-2xl font-bold text-indigo-700">{czscData.score}</span>
                      <span className="text-xs text-muted-foreground">/ 100</span>
                    </div>
                  )}
                  {czscData.buy_point_info?.buy_points?.length > 0 && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-muted-foreground">买点:</span>
                      {(czscData.buy_point_info.buy_points as string[]).map((b, i) => {
                        const high = b.includes("高位");
                        const cls = high
                          ? "px-2 py-0.5 text-xs bg-amber-500/15 text-amber-700 rounded border border-amber-500/40 font-medium"
                          : "px-2 py-0.5 text-xs bg-green-500/15 text-green-700 rounded border border-green-500/30 font-medium";
                        return <span key={i} className={cls}>{b}</span>;
                      })}
                    </div>
                  )}
                  {czscData.safe_to_buy === false && czscData.zg > 0 && (
                    <div className="px-3 py-1.5 rounded-lg border bg-amber-500/10 border-amber-500/30 flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-amber-600" />
                      <span className="text-xs text-amber-700 font-medium">
                        价格脱离中枢安全区 · 上限 {(czscData.safe_price_max ?? 0).toFixed(2)}
                      </span>
                    </div>
                  )}
                  {czscData.buy_point_info && (
                    <div className="text-xs text-muted-foreground flex gap-3 flex-wrap">
                      <span>笔数: <strong className="text-foreground">{czscData.buy_point_info.bi_count}</strong></span>
                      <span>中枢: <strong className="text-foreground">{czscData.buy_point_info.zs_count}</strong></span>
                      <span>
                        方向: {
                          czscData.buy_point_info.last_bi_dir === "up" ? <strong className="text-green-600">↑向上</strong> :
                          czscData.buy_point_info.last_bi_dir === "down" ? <strong className="text-red-600">↓向下</strong> :
                          <strong className="text-foreground">-</strong>
                        }
                      </span>
                      <span>
                        位置: {
                          czscData.buy_point_info.in_zs ? <span className="text-indigo-700">中枢内</span> :
                          czscData.buy_point_info.zs_range ? (
                            (czscData.analysis?.price ?? 0) > czscData.buy_point_info.zs_range[1]
                              ? (czscData.safe_to_buy === false
                                  ? <span className="text-amber-600 font-medium">中枢上方（高位）</span>
                                  : <span className="text-green-600">中枢上方（三买区）</span>)
                              : <span className="text-red-600">中枢下方</span>
                          ) : <span className="text-muted-foreground">未形成中枢</span>
                        }
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* 图表 */}
              {czscLoading ? (
                <div className="h-96 flex items-center justify-center text-muted-foreground">加载中...</div>
              ) : czscData?.klines ? (
                (() => {
                  const buyPoints: CzscBuyPoint[] = [];
                  const bis: CzscBi[] = czscData.bis || [];
                  // 优先用后端返回的真实买卖点坐标 (落在真实摆动位)
                  const marks = czscData.buy_point_info?.buy_point_marks as
                    | { label: string; date: string; price: number; kind: string; live?: boolean }[]
                    | undefined;
                  if (marks && marks.length > 0) {
                    for (const m of marks) {
                      buyPoints.push({ date: m.date, type: m.label, price: m.price, live: m.live });
                    }
                  } else {
                    // 回退: 旧逻辑 (画在最后一笔端点)
                    const buyTypes: string[] = czscData.buy_point_info?.buy_points || [];
                    const lastBi = bis[bis.length - 1];
                    if (lastBi && buyTypes.length > 0) {
                      for (const t of buyTypes) {
                        const isBuy = /买/.test(t);
                        buyPoints.push({
                          date: lastBi.edt,
                          type: t,
                          price: isBuy ? lastBi.low : lastBi.high,
                        });
                      }
                    }
                  }
                  return (
                    <CzscChart
                      klines={czscData.klines as CzscKline[]}
                      bis={bis}
                      zsList={(czscData.zs_list || []) as CzscZS[]}
                      buyPoints={buyPoints}
                      height={420}
                    />
                  );
                })()
              ) : (
                <div className="h-96 flex items-center justify-center text-muted-foreground">暂无缠论数据</div>
              )}

              {/* 分析建议 */}
              {czscData?.analysis && (
                <div className="mt-2 p-3 bg-muted/30 rounded-lg text-sm">
                  <div className="flex items-center gap-4 mb-2 text-xs text-muted-foreground flex-wrap">
                    <span>日期: {czscData.analysis.date}</span>
                    <span>收盘价: <strong className="text-foreground">{Number(czscData.analysis.price).toFixed(2)}</strong></span>
                  </div>
                  <div className="space-y-1 mb-2">
                    {(czscData.analysis.points || []).map((p: string, i: number) => (
                      <div key={i} className="flex items-start gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-primary mt-1.5 shrink-0" />
                        <span>{p}</span>
                      </div>
                    ))}
                  </div>
                  <div className="font-medium text-primary">
                    {czscData.analysis.suggestion}
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

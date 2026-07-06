import { useEffect, useState } from "react";
import { Plus, RefreshCw, Zap, Trash2, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";

interface Stock {
  code: string;
  name: string;
  prev_close: number;
  status: string;
  E?: number;
  stop?: number;
}

interface AuctionData {
  code: string;
  name: string;
  auction_price: number;
  auction_change_pct: number;
  today_vol: number;
  prev_vol: number;
  vol_ratio: number;
  expectation: string;
  suggestion: string;
}

export function Expectations() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [auctionData, setAuctionData] = useState<AuctionData[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [collecting, setCollecting] = useState(false);
  const [editingVol, setEditingVol] = useState<Record<string, { today: number; prev: number }>>({});
  const [auctionMap, setAuctionMap] = useState<Record<string, { today_vol: number; prev_vol: number; prev_volume: number; auction_ratio: number; auction_price?: number }>>({});
  const { t } = useTranslation();
  const renderExpectation = (type: string) => {
    switch (type) {
      case "aboveExpectations": return t("expectations.aboveExpectations");
      case "meetsExpectations": return t("expectations.meetsExpectations");
      case "belowExpectations": return t("expectations.belowExpectations");
      default: return t("expectations.normal");
    }
  };
  const renderSuggestion = (key: string) => {
    switch (key) {
      case "increaseHold": return t("expectations.increaseHold");
      case "observe": return t("expectations.observe");
      case "cutLosses": return t("expectations.cutLosses");
      default: return t("expectations.wait");
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>("/expectations");
      const pos = data.positions || [];
      setStocks(pos);
      // Fetch auction data for these stocks
      if (pos.length > 0) {
        const codes = pos.map((s: Stock) => s.code).join(",");
        const aData = await api.tools.get<any>(`/watchlist-auction?codes=${codes}`);
        setAuctionMap(aData.auction || {});
      }
    } catch (e) {
      console.error('Failed to fetch expectations:', e);
    } finally {
      setLoading(false);
    }
  };

  const fetchAuction = async () => {
    setCollecting(true);
    try {
      const data = await api.tools.post<any>("/expectations/collect-auction");
      setAuctionData(data.stocks || []);
    } catch (e) {
      console.error('Failed to collect auction:', e);
    } finally {
      setCollecting(false);
    }
  };

  const addStock = async () => {
    if (!newCode.trim()) return;
    try {
      await api.tools.post<any>("/expectations/add", { code: newCode.trim() });
      setNewCode("");
      setShowAddModal(false);
      fetchData();
    } catch (e) {
      console.error('Failed to add stock:', e);
    }
  };

  const removeStock = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/remove", { code });
      fetchData();
    } catch (e) {
      console.error('Failed to remove stock:', e);
    }
  };

  const saveAuctionVol = async (code: string) => {
    const vol = editingVol[code];
    if (!vol) return;
    try {
      await api.tools.post<any>("/expectations/save-auction", { code, today_vol: vol.today, prev_vol: vol.prev });
      fetchData();
    } catch (e) {
      console.error('Failed to save auction vol:', e);
    }
  };

  const updateEditingVol = (code: string, field: "today" | "prev", value: number) => {
    setEditingVol((prev) => ({
      ...prev,
      [code]: { ...prev[code], [field]: value },
    }));
  };

  const calcExpectation = (changePct: number, volRatio: number) => {
    if (changePct > 3 && volRatio >= 1.5) return { type: "aboveExpectations", color: "text-red-600" };
    if (changePct >= -1 && changePct <= 1 && volRatio >= 0.8 && volRatio <= 1.2) return { type: "meetsExpectations", color: "text-green-600" };
    if (changePct < -1 || volRatio < 0.7) return { type: "belowExpectations", color: "text-yellow-600" };
    return { type: "normal", color: "text-muted-foreground" };
  };

  const calcSuggestionKey = (expectation: string) => {
    switch (expectation) {
      case "aboveExpectations": return "increaseHold";
      case "meetsExpectations": return "observe";
      case "belowExpectations": return "cutLosses";
      default: return "wait";
    }
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("expectations.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("expectations.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t("expectations.addStock")}
          </button>
          <button
            onClick={fetchAuction}
            disabled={collecting}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-purple-600 text-white rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
          >
            <Zap className={`h-4 w-4 ${collecting ? "animate-spin" : ""}`} />
            {t("expectations.collectAuction")}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("expectations.refresh")}
          </button>
        </div>
      </div>

      {/* 竞价数据表格 */}
      {auctionData.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <h2 className="font-semibold">{t("expectations.auctionData")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t("expectations.thCode")}</th>
                  <th className="px-3 py-2 text-left font-medium">{t("expectations.thName")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thAuctionPrice")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thAuctionChange")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thTodayVol")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thPrevVol")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thVolRatio")}</th>
                  <th className="px-3 py-2 text-center font-medium">{t("expectations.thExpectation")}</th>
                  <th className="px-3 py-2 text-center font-medium">{t("expectations.thSuggestion")}</th>
                  <th className="px-3 py-2 text-center font-medium">{t("expectations.thAction")}</th>
                </tr>
              </thead>
              <tbody>
                {auctionData.map((item) => {
                  const vol = editingVol[item.code] || { today: item.today_vol, prev: item.prev_vol };
                  const ratio = vol.prev > 0 ? vol.today / vol.prev : 0;
                  const expectation = calcExpectation(item.auction_change_pct, ratio);
                  const suggestionKey = calcSuggestionKey(expectation.type);
                  return (
                    <tr key={item.code} className="border-t">
                      <td className="px-3 py-2 font-mono">{item.code}</td>
                      <td className="px-3 py-2">{item.name}</td>
                      <td className="px-3 py-2 text-right">{item.auction_price.toFixed(2)}</td>
                      <td className={`px-3 py-2 text-right ${item.auction_change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {item.auction_change_pct >= 0 ? "+" : ""}{item.auction_change_pct.toFixed(2)}%
                      </td>
                      <td className="px-3 py-2 text-right">
                        <input
                          type="number"
                          value={vol.today}
                          onChange={(e) => updateEditingVol(item.code, "today", Number(e.target.value))}
                          className="w-20 text-right border rounded px-1 py-0.5 text-xs"
                        />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <input
                          type="number"
                          value={vol.prev}
                          onChange={(e) => updateEditingVol(item.code, "prev", Number(e.target.value))}
                          className="w-20 text-right border rounded px-1 py-0.5 text-xs"
                        />
                      </td>
                      <td className="px-3 py-2 text-right">{ratio.toFixed(2)}</td>
                      <td className={`px-3 py-2 text-center font-medium ${expectation.color}`}>
                        {renderExpectation(expectation.type)}
                      </td>
                      <td className="px-3 py-2 text-center">{renderSuggestion(suggestionKey)}</td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => saveAuctionVol(item.code)}
                          className="p-1 text-primary hover:bg-primary/10 rounded"
                          title={t("expectations.save")}
                        >
                          <Save className="h-4 w-4" />
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

      {/* 自选股列表 */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b bg-muted/30">
          <h2 className="font-semibold">{t("expectations.stockList")}</h2>
        </div>
        {stocks.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            {t("expectations.emptyHint")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">{t("expectations.thCode")}</th>
                  <th className="px-3 py-2 text-left font-medium">{t("expectations.thName")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thPrevClose")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thTodayVol")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thPrevVol")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thPrevVolume")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("expectations.thAuctionChange")}</th>
                  <th className="px-3 py-2 text-center font-medium">{t("expectations.thAction")}</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((stock) => {
                  const a = auctionMap[stock.code] || {};
                  const todayVol = a.today_vol || 0;
                  const prevVol = a.prev_vol || 0;
                  const prevVolume = a.prev_volume || 0;
                  const auctionChg = stock.prev_close > 0 && (a.auction_price ?? 0) > 0
                    ? (((a.auction_price ?? 0) - stock.prev_close) / stock.prev_close * 100)
                    : null;
                  return (
                    <tr key={stock.code} className="border-t">
                      <td className="px-3 py-2 font-mono">{stock.code}</td>
                      <td className="px-3 py-2">{stock.name}</td>
                      <td className="px-3 py-2 text-right">{stock.prev_close?.toFixed(2) || "-"}</td>
                      <td className="px-3 py-2 text-right font-medium">
                        {todayVol ? todayVol.toLocaleString() : "-"}
                      </td>
                      <td className="px-3 py-2 text-right text-muted-foreground">
                        {prevVol ? prevVol.toLocaleString() : "-"}
                      </td>
                      <td className="px-3 py-2 text-right text-muted-foreground">
                        {prevVolume ? prevVolume.toLocaleString() : "-"}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${auctionChg >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {prevVol > 0 ? `${auctionChg >= 0 ? "+" : ""}${auctionChg.toFixed(1)}%` : "-"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => removeStock(stock.code)}
                          className="p-1 text-muted-foreground hover:text-red-600 rounded"
                          title={t("expectations.delete")}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg p-6 w-96 shadow-lg">
            <h3 className="text-lg font-semibold mb-4">{t("expectations.addStockTitle")}</h3>
            <input
              autoFocus
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addStock(); if (e.key === "Escape") setShowAddModal(false); }}
              placeholder={t("expectations.searchPlaceholder")}
              className="w-full border rounded-md px-3 py-2 text-sm mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm border rounded-md hover:bg-muted"
              >
                {t("expectations.cancel")}
              </button>
              <button
                onClick={addStock}
                className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90"
              >
                {t("expectations.add")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

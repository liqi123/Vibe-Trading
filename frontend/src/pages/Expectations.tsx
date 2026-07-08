import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, RefreshCw, Zap, Trash2, Save } from "lucide-react";

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
  const [auctionMap, setAuctionMap] = useState<Record<string, { today_vol: number; prev_vol: number; prev_volume: number; auction_price?: number }>>({});

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch("/tools/expectations");
      if (res.ok) {
        const data = await res.json();
        const pos = data.positions || [];
        setStocks(pos);
        // Fetch auction data for these stocks
        if (pos.length > 0) {
          const codes = pos.map((s: Stock) => s.code).join(",");
          const aRes = await fetch(`/tools/watchlist-auction?codes=${codes}`);
          if (aRes.ok) {
            const aData = await aRes.json();
            const merged = { ...(aData.auction || {}) };
            // Merge manually saved auction_data so user edits override DB data
            const saved = data.auction_data || {};
            for (const [code, v] of Object.entries(saved)) {
              if (!merged[code]) merged[code] = {};
              merged[code].today_vol = (v as any).today_vol ?? merged[code].today_vol;
              merged[code].prev_vol = (v as any).prev_vol ?? merged[code].prev_vol;
              merged[code].auction_price = (v as any).auction_price ?? merged[code].auction_price;
            }
            setAuctionMap(merged);
          }
        }
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const fetchAuction = async () => {
    setCollecting(true);
    try {
      const res = await fetch("/tools/expectations/collect-auction", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.status === "no_data") {
          toast.error("今日尚无竞价数据（09:30后无法采集）");
        } else if (data.status === "exists") {
          toast.info("已使用今日已有竞价数据");
        }
        setAuctionData(data.stocks || []);
      }
    } catch {
      // ignore
    } finally {
      setCollecting(false);
    }
  };

  const addStock = async () => {
    if (!newCode.trim()) return;
    try {
      await fetch("/tools/expectations/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: newCode.trim() }),
      });
      setNewCode("");
      setShowAddModal(false);
      fetchData();
    } catch {
      // ignore
    }
  };

  const removeStock = async (code: string) => {
    try {
      await fetch("/tools/expectations/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      fetchData();
    } catch {
      // ignore
    }
  };

  const saveAuctionVol = async (code: string) => {
    const vol = editingVol[code];
    if (!vol) return;
    try {
      await fetch("/tools/expectations/save-auction", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, today_vol: Math.round(vol.today), prev_vol: Math.round(vol.prev) }),
      });
      fetchData();
    } catch {
      // ignore
    }
  };

  const updateEditingVol = (code: string, field: "today" | "prev", value: number) => {
    setEditingVol((prev) => ({
      ...prev,
      [code]: { ...prev[code], [field]: value },
    }));
  };

  const calcExpectation = (changePct: number, volRatio: number) => {
    if (changePct > 3 && volRatio >= 1.5) return { type: "超预期", color: "text-red-600" };
    if (changePct >= -1 && changePct <= 1 && volRatio >= 0.8 && volRatio <= 1.2) return { type: "符合预期", color: "text-green-600" };
    if (changePct < -1 || volRatio < 0.7) return { type: "不及预期", color: "text-yellow-600" };
    return { type: "正常", color: "text-muted-foreground" };
  };

  const calcSuggestion = (expectation: string) => {
    switch (expectation) {
      case "超预期": return "加仓/持有";
      case "符合预期": return "观察3-5分钟";
      case "不及预期": return "反抽减亏";
      default: return "观望";
    }
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">预期管理</h1>
          <p className="text-sm text-muted-foreground mt-1">自选股竞价监控与预期判断</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            添加自选股
          </button>
          <button
            onClick={fetchAuction}
            disabled={collecting}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-purple-600 text-white rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
          >
            <Zap className={`h-4 w-4 ${collecting ? "animate-spin" : ""}`} />
            采集竞价数据
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
      </div>

      {/* 竞价数据表格 */}
      {auctionData.length > 0 && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <h2 className="font-semibold">竞价数据</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">竞价价</th>
                  <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                  <th className="px-3 py-2 text-right font-medium">今日竞价量（手）</th>
                  <th className="px-3 py-2 text-right font-medium">昨日竞价量（手）</th>
                  <th className="px-3 py-2 text-right font-medium">量比</th>
                  <th className="px-3 py-2 text-center font-medium">预期</th>
                  <th className="px-3 py-2 text-center font-medium">建议</th>
                  <th className="px-3 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {auctionData.map((item) => {
                  const vol = editingVol[item.code] || { today: Math.round(item.today_vol), prev: Math.round(item.prev_vol) };
                  const ratio = vol.prev > 0 ? vol.today / vol.prev : 0;
                  const expectation = calcExpectation(item.auction_change_pct, ratio);
                  const suggestion = calcSuggestion(expectation.type);
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
                        {expectation.type}
                      </td>
                      <td className="px-3 py-2 text-center">{suggestion}</td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => saveAuctionVol(item.code)}
                          className="p-1 text-primary hover:bg-primary/10 rounded"
                          title="保存"
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
          <h2 className="font-semibold">自选股列表</h2>
        </div>
        {stocks.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            暂无自选股，点击"添加自选股"开始
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">今日竞价量（手）</th>
                  <th className="px-3 py-2 text-right font-medium">昨日竞价量（手）</th>
                  <th className="px-3 py-2 text-right font-medium">量比</th>
                  <th className="px-3 py-2 text-right font-medium">昨日成交量</th>
                  <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                  <th className="px-3 py-2 text-center font-medium">推荐操作</th>
                  <th className="px-3 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((stock) => {
                  const a = auctionMap[stock.code] || {};
                  const todayVol = Math.round(a.today_vol || 0);
                  const prevVol = Math.round(a.prev_vol || 0);
                  const volRatio = prevVol > 0 ? todayVol / prevVol : 0;
                  const prevVolume = a.prev_volume || 0;
                  const auctionChg = stock.prev_close > 0 && (a.auction_price ?? 0) > 0
                    ? ((a.auction_price! - stock.prev_close) / stock.prev_close * 100)
                    : null;
                  const expType = auctionChg != null
                    ? calcExpectation(auctionChg, volRatio)
                    : null;
                  const suggestion = expType ? calcSuggestion(expType.type) : "";
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
                      <td className={`px-3 py-2 text-right font-medium ${volRatio > 1 ? "text-red-600" : volRatio > 0 && volRatio < 1 ? "text-green-600" : ""}`}>
                        {volRatio > 0 ? volRatio.toFixed(2) : "-"}
                      </td>
                      <td className="px-3 py-2 text-right text-muted-foreground">
                        {prevVolume ? prevVolume.toLocaleString() : "-"}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${auctionChg != null && auctionChg >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {auctionChg != null ? `${auctionChg >= 0 ? "+" : ""}${auctionChg.toFixed(2)}%` : "-"}
                      </td>
                      <td className={`px-3 py-2 text-center font-medium ${expType?.color || ""}`}>
                        {suggestion || "-"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => removeStock(stock.code)}
                          className="p-1 text-muted-foreground hover:text-red-600 rounded"
                          title="删除"
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
            <h3 className="text-lg font-semibold mb-4">添加自选股</h3>
            <input
              autoFocus
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addStock(); if (e.key === "Escape") setShowAddModal(false); }}
              placeholder="输入股票代码，如 sh600519"
              className="w-full border rounded-md px-3 py-2 text-sm mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm border rounded-md hover:bg-muted"
              >
                取消
              </button>
              <button
                onClick={addStock}
                className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

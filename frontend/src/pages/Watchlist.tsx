import { useEffect, useState } from "react";
import { Plus, RefreshCw, Trash2, Edit2, Check, X } from "lucide-react";
import { useModalStore } from "../stores/modal";

interface WatchlistItem {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  e_price: number;
  x_price: number;
  runaway_price: number;
}

  const PHI = (1 + Math.sqrt(5)) / 2;
  const fibonacciPrice = (H: number, L: number, n = 5) => {
    const factor = 1 / PHI + Math.exp((-2 * Math.log(PHI)) / Math.PI * n);
    return H - factor * (H - L);
  };

  const getSuggestion = (price: number, e: number, x: number, run: number): { text: string; color: string } => {
    if (!price || !e) return { text: "-", color: "text-muted-foreground" };
    if (price < e) return { text: "买入", color: "text-green-600 font-bold" };
    if (x && price >= x && (!run || price < run)) return { text: "考虑卖出", color: "text-orange-600 font-bold" };
    if (run && price >= run) return { text: "建议卖出", color: "text-red-600 font-bold" };
    return { text: "持有", color: "text-blue-600" };
  };

export function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [searchResults, setSearchResults] = useState<{code: string; name: string}[]>([]);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [editValues, setEditValues] = useState({ e_price: "", x_price: "", runaway_price: "" });
  const openStock = useModalStore((s) => s.open);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch("/tools/expectations");
      if (res.ok) {
        const data = await res.json();
        const positions = data.positions || [];
        if (positions.length > 0) {
          const codes = positions.map((p: any) => p.code).join(",");
          const priceRes = await fetch(`/tools/prices?codes=${codes}`);
          if (priceRes.ok) {
            const priceData = await priceRes.json();
            const enriched = positions.map((p: any) => {
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
            setItems(positions.map((p: any) => ({
              code: p.code,
              name: p.name || "",
              price: 0,
              change_pct: 0,
              e_price: p.e_price || 0,
              x_price: p.x_price || 0,
              runaway_price: p.runaway_price || 0,
            })));
          }
        } else {
          setItems([]);
        }
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const searchStock = async (q: string) => {
    if (!q.trim()) { setSearchResults([]); return; }
    try {
      const res = await fetch(`/tools/expectations/search?q=${encodeURIComponent(q.trim())}`);
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results || []);
      }
    } catch { /* ignore */ }
  };

  const addStock = async (code?: string) => {
    const input = code || newCode.trim();
    if (!input) return;
    try {
      await fetch("/tools/expectations/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: input }),
      });
      setNewCode("");
      setSearchResults([]);
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
      await fetch("/tools/expectations/update-prices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          e_price: parseFloat(editValues.e_price) || 0,
          x_price: parseFloat(editValues.x_price) || 0,
          runaway_price: parseFloat(editValues.runaway_price) || 0,
        }),
      });
      setEditingCode(null);
      fetchData();
    } catch {
      // ignore
    }
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
          <h1 className="text-2xl font-bold">自选股</h1>
          <p className="text-sm text-muted-foreground mt-1">实时行情监控</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            添加
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

      <div className="border rounded-lg bg-card overflow-hidden">
        {items.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            暂无自选股，点击"添加"开始
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">代码</th>
                  <th className="px-4 py-3 text-left font-medium">名称</th>
                  <th className="px-4 py-3 text-right font-medium">现价</th>
                  <th className="px-4 py-3 text-right font-medium">涨跌幅</th>
                  <th className="px-4 py-3 text-right font-medium">E价</th>
                  <th className="px-4 py-3 text-right font-medium">X价</th>
                  <th className="px-4 py-3 text-right font-medium">跑路价</th>
                  <th className="px-4 py-3 text-center font-medium">建议</th>
                  <th className="px-4 py-3 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isEditing = editingCode === item.code;
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
                        <span className={`text-xs ${getSuggestion(item.price, item.e_price, item.x_price, item.runaway_price).color}`}>
                          {getSuggestion(item.price, item.e_price, item.x_price, item.runaway_price).text}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isEditing ? (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => saveEdit(item.code)}
                              className="p-1 text-green-600 hover:bg-green-100 rounded transition-colors"
                              title="保存"
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              onClick={cancelEdit}
                              className="p-1 text-muted-foreground hover:bg-muted rounded transition-colors"
                              title="取消"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => startEdit(item)}
                              className="p-1 text-muted-foreground hover:text-blue-600 rounded transition-colors"
                              title="编辑"
                            >
                              <Edit2 className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => removeStock(item.code)}
                              className="p-1 text-muted-foreground hover:text-red-600 rounded transition-colors"
                              title="删除"
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
            <h3 className="text-lg font-semibold mb-4">添加自选股</h3>
            <input
              autoFocus
              value={newCode}
              onChange={(e) => { setNewCode(e.target.value); searchStock(e.target.value); }}
              onKeyDown={(e) => { if (e.key === "Enter") addStock(); if (e.key === "Escape") setShowAddModal(false); }}
              placeholder="输入代码或名称，如 000725 / 京东方"
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
                取消
              </button>
              <button
                onClick={() => addStock()}
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

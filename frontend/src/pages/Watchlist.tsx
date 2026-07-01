import { useEffect, useState } from "react";
import { Star, Plus, Trash2, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";

interface WatchItem {
  code: string;
  name: string;
  current_price: number;
  change_pct: number;
  added_date: string;
}

const STORAGE_KEY = "trading_watchlist";

function loadWatchlist(): WatchItem[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch { return []; }
}

function saveWatchlist(list: WatchItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

export function Watchlist() {
  const [list, setList] = useState<WatchItem[]>([]);
  const [addCode, setAddCode] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { setList(loadWatchlist()); }, []);

  const addStock = async () => {
    const code = addCode.trim();
    if (!code) return;
    if (list.some(w => w.code === code)) { setAddCode(""); return; }

    setLoading(true);
    try {
      const res = await fetch(`/tools/stock/${code}`);
      const data = await res.json();
      const item: WatchItem = {
        code,
        name: data.name || code,
        current_price: data.kline?.[0]?.close || 0,
        change_pct: data.kline?.[0] && data.kline?.[1]
          ? (data.kline[0].close - data.kline[1].close) / data.kline[1].close * 100
          : 0,
        added_date: new Date().toISOString().slice(0, 10),
      };
      const newList = [item, ...list];
      setList(newList);
      saveWatchlist(newList);
    } catch { /* ignore */ }
    setAddCode("");
    setLoading(false);
  };

  const removeStock = (code: string) => {
    const newList = list.filter(w => w.code !== code);
    setList(newList);
    saveWatchlist(newList);
  };

  const refreshPrices = async () => {
    setLoading(true);
    const updated = await Promise.all(
      list.map(async (item) => {
        try {
          const res = await fetch(`/tools/stock/${item.code}`);
          const data = await res.json();
          return {
            ...item,
            name: data.name || item.name,
            current_price: data.kline?.[0]?.close || item.current_price,
            change_pct: data.kline?.[0] && data.kline?.[1]
              ? (data.kline[0].close - data.kline[1].close) / data.kline[1].close * 100
              : item.change_pct,
          };
        } catch { return item; }
      })
    );
    setList(updated);
    saveWatchlist(updated);
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">自选股</h1>
          <p className="text-sm text-muted-foreground mt-1">关注股票列表</p>
        </div>
        <button
          onClick={refreshPrices}
          disabled={loading || list.length === 0}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {/* Add stock */}
      <div className="flex gap-2">
        <input
          value={addCode}
          onChange={(e) => setAddCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addStock()}
          placeholder="输入股票代码，如 sz301618"
          className="flex-1 px-3 py-2 text-sm border rounded-md bg-background outline-none focus:ring-2 focus:ring-primary/30"
        />
        <button
          onClick={addStock}
          disabled={!addCode.trim() || loading}
          className="flex items-center gap-1.5 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          添加
        </button>
      </div>

      {/* Watchlist table */}
      {list.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <Star className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p>暂无自选股，输入代码添加</p>
        </div>
      ) : (
        <div className="border rounded-lg bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium">代码</th>
                <th className="px-4 py-2 text-left font-medium">名称</th>
                <th className="px-4 py-2 text-right font-medium">现价</th>
                <th className="px-4 py-2 text-right font-medium">涨跌</th>
                <th className="px-4 py-2 text-left font-medium">添加日期</th>
                <th className="px-4 py-2 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {list.map((item) => (
                <tr key={item.code} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-3 font-mono text-xs">{item.code}</td>
                  <td className="px-4 py-3 font-medium">{item.name}</td>
                  <td className="px-4 py-3 text-right">{item.current_price?.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`inline-flex items-center gap-1 ${item.change_pct >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {item.change_pct >= 0
                        ? <TrendingUp className="h-3 w-3" />
                        : <TrendingDown className="h-3 w-3" />}
                      {item.change_pct >= 0 ? "+" : ""}{item.change_pct.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{item.added_date}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => removeStock(item.code)}
                      className="p-1 text-muted-foreground hover:text-red-500 rounded"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

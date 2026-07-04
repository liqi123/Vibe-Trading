import { useState } from "react";
import { Newspaper, Search, Loader2, ExternalLink } from "lucide-react";

interface NewsItem {
  title?: string;
  content?: string;
  source?: string;
  time?: string;
  url?: string;
}

export function NewsSearch() {
  const [query, setQuery] = useState("");
  const [stockCode, setStockCode] = useState("");
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async (byCode = false) => {
    const q = byCode ? stockCode : query;
    if (!q.trim()) return;
    setLoading(true);
    setItems([]);
    setSearched(true);
    try {
      const url = byCode
        ? `/tools/news?stock_code=${encodeURIComponent(q.trim())}`
        : `/tools/news?q=${encodeURIComponent(q.trim())}`;
      const res = await fetch(url);
      const data = await res.json();
      setItems(data.items || []);
    } catch { /* ignore */ }
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">新闻查询</h1>
        <p className="text-sm text-muted-foreground mt-1">多源新闻聚合搜索</p>
      </div>

      {/* General Search */}
      <div className="border rounded-lg p-5 bg-card space-y-3">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-blue-500" />
          <h3 className="font-semibold">关键词搜索</h3>
        </div>
        <div className="flex gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch(false)}
            placeholder="输入关键词搜索新闻"
            className="flex-1 px-3 py-2 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
          <button onClick={() => handleSearch(false)} disabled={loading || !query.trim()}
            className="flex items-center gap-1 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50">
            <Search className="h-4 w-4" />搜索
          </button>
        </div>
      </div>

      {/* Stock News */}
      <div className="border rounded-lg p-5 bg-card space-y-3">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-green-500" />
          <h3 className="font-semibold">个股新闻</h3>
        </div>
        <div className="flex gap-2">
          <input value={stockCode} onChange={(e) => setStockCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch(true)}
            placeholder="输入股票代码，如 sh600519"
            className="flex-1 px-3 py-2 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
          <button onClick={() => handleSearch(true)} disabled={loading || !stockCode.trim()}
            className="flex items-center gap-1 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50">
            <Search className="h-4 w-4" />查询
          </button>
        </div>
      </div>

      {/* Results */}
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {!loading && searched && items.length === 0 && (
        <p className="text-center text-muted-foreground py-8">未找到相关新闻</p>
      )}

      {!loading && items.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold">搜索结果（{items.length} 条）</h3>
          {items.map((item, i) => (
            <div key={i} className="border rounded-lg p-4 bg-card hover:bg-muted/30 transition-colors">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <h4 className="font-medium text-sm">{item.title || "无标题"}</h4>
                  {item.content && (
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{item.content}</p>
                  )}
                  <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                    {item.source && <span>{item.source}</span>}
                    {item.time && <span>{item.time}</span>}
                  </div>
                </div>
                {item.url && (
                  <a href={item.url} target="_blank" rel="noopener noreferrer"
                    className="shrink-0 p-1 text-muted-foreground hover:text-primary">
                    <ExternalLink className="h-4 w-4" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

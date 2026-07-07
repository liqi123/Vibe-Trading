import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, Layers, Grid3X3 } from "lucide-react";
import { api } from "@/lib/api";

interface LadderStock {
  code: string; name: string; price: number; chg_pct: number;
  board: number; amount: number; volume: number; concepts: string[];
}

interface LadderStats {
  total_limit_up: number; first_board: number; continue_up: number;
  max_board: number; board_distribution: Record<string, number>;
}

export function MarketLadder() {
  const [ladder, setLadder] = useState<LadderStock[]>([]);
  const [byBoard, setByBoard] = useState<Record<string, LadderStock[]>>({});
  const [byConcept, setByConcept] = useState<Record<string, LadderStock[]>>({});
  const [stats, setStats] = useState<LadderStats | null>(null);
  const [summary, setSummary] = useState("");
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"board" | "concept">("board");

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>("/market/ladder");
      setLadder(data.ladder || []);
      setByBoard(data.by_board || {});
      setByConcept(data.by_concept || {});
      setStats(data.stats || null);
      setSummary(data.summary || "");
    } catch (e) { console.error('Failed to fetch ladder:', e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const formatAmount = (v: number) => {
    if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
    return String(v);
  };

  const boardColors: Record<number, string> = {
    1: "bg-gray-100 text-gray-700 border-gray-200",
    2: "bg-blue-50 text-blue-700 border-blue-200",
    3: "bg-purple-50 text-purple-700 border-purple-200",
    4: "bg-orange-50 text-orange-700 border-orange-200",
    5: "bg-red-50 text-red-700 border-red-200",
  };

  const boardBadge = (n: number) => {
    const colors = boardColors[n] || "bg-pink-50 text-pink-700 border-pink-200";
    return (
      <span className={`inline-block px-2 py-0.5 text-xs font-bold rounded border ${colors}`}>
        {n === 1 ? "首板" : `${n}板`}
      </span>
    );
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Layers className="h-6 w-6" />
            连板梯队
          </h1>
          <p className="text-sm text-muted-foreground mt-1">涨停板高度与题材聚类分析</p>
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

      {summary && <div className="text-sm text-muted-foreground">{summary}</div>}

      {/* Stats Cards */}
      {stats && (
        <div className="grid gap-4 grid-cols-2 md:grid-cols-5">
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">涨停总数</div>
            <p className="text-xl font-bold text-red-600">{stats.total_limit_up}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">首板</div>
            <p className="text-xl font-bold">{stats.first_board}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">连板</div>
            <p className="text-xl font-bold text-purple-600">{stats.continue_up}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">最高板</div>
            <p className="text-xl font-bold text-orange-600">{stats.max_board}板</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">板数分布</div>
            <p className="text-xs font-mono">
              {Object.entries(stats.board_distribution).sort(([a], [b]) => +b - +a).map(([k, v]) => (
                <span key={k} className="mr-2">{k}板:{v}</span>
              ))}
            </p>
          </div>
        </div>
      )}

      {/* View Toggle */}
      <div className="flex items-center gap-1 border-b">
        {[
          { key: "board" as const, label: "按板数", icon: Layers },
          { key: "concept" as const, label: "按概念", icon: Grid3X3 },
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
              view === key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {loading && ladder.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground">加载中...</div>
      ) : ladder.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground">暂无涨停数据</div>
      ) : view === "board" ? (
        /* Board view */
        <div className="space-y-4">
          {Object.entries(byBoard).sort(([a], [b]) => +b - +a).map(([board, stocks]) => (
            <div key={board} className="border rounded-lg bg-card overflow-hidden">
              <div className="px-4 py-2 border-b bg-muted/30 flex items-center gap-2">
                {boardBadge(+board)}
                <span className="text-xs text-muted-foreground">{stocks.length}只</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">代码</th>
                      <th className="px-3 py-2 text-left font-medium">名称</th>
                      <th className="px-3 py-2 text-right font-medium">现价</th>
                      <th className="px-3 py-2 text-right font-medium">涨幅</th>
                      <th className="px-3 py-2 text-right font-medium">成交额</th>
                      <th className="px-3 py-2 text-left font-medium">概念</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stocks.map((s) => (
                      <tr key={s.code} className="border-t hover:bg-muted/30">
                        <td className="px-3 py-2 font-mono">{s.code.replace(/^(sh|sz)/, "")}</td>
                        <td className="px-3 py-2">{s.name}</td>
                        <td className="px-3 py-2 text-right font-mono">{s.price.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right text-red-600 font-medium">{s.chg_pct >= 0 ? "+" : ""}{s.chg_pct.toFixed(1)}%</td>
                        <td className="px-3 py-2 text-right">{formatAmount(s.amount)}</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">{(s.concepts || []).slice(0, 2).join(", ")}{(s.concepts || []).length > 2 ? "..." : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Concept view */
        <div className="space-y-6">
          {Object.entries(byConcept).sort(([, a], [, b]) => b.length - a.length).map(([concept, stocks]) => (
            <div key={concept} className="border-2 border-blue-100 rounded-xl bg-card overflow-hidden shadow-md">
              <div className="px-5 py-3 border-b bg-gradient-to-r from-blue-50 to-white flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-red-500" />
                <span className="font-semibold text-base">{concept}</span>
                <span className="text-xs text-muted-foreground ml-auto">{stocks.length}只涨停</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">代码</th>
                      <th className="px-3 py-2 text-left font-medium">名称</th>
                      <th className="px-3 py-2 text-right font-medium">现价</th>
                      <th className="px-3 py-2 text-center font-medium">板数</th>
                      <th className="px-3 py-2 text-right font-medium">成交额</th>
                      <th className="px-3 py-2 text-left font-medium">概念</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stocks.map((s) => (
                      <tr key={s.code} className="border-t hover:bg-muted/30">
                        <td className="px-3 py-2 font-mono">{s.code.replace(/^(sh|sz)/, "")}</td>
                        <td className="px-3 py-2">{s.name}</td>
                        <td className="px-3 py-2 text-right font-mono">{s.price.toFixed(2)}</td>
                        <td className="px-3 py-2 text-center">{boardBadge(s.board)}</td>
                        <td className="px-3 py-2 text-right">{formatAmount(s.amount)}</td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">{(s.concepts || []).slice(0, 3).join(", ")}{(s.concepts || []).length > 3 ? "..." : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

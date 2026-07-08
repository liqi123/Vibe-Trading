import { useEffect, useState } from "react";
import { Search, RefreshCw, TrendingUp, Download, CandlestickChart as CandleIcon } from "lucide-react";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { api } from "@/lib/api";
import type { PriceBar } from "@/lib/api";

interface MarketStats {
  total: number;
  up: number;
  down: number;
  flat: number;
  limit_up: number;
  limit_down: number;
}

interface Candidate {
  code: string;
  name: string;
  price: number;
  score: number;
  E?: number;
  deviation?: number;
  H?: number;
  L?: number;
  H_date?: string;
  L_date?: string;
  swing?: number;
  stop?: number;
}

interface Column {
  key: string;
  label: string;
  align?: "left" | "right" | "center";
  render: (c: Candidate) => React.ReactNode;
}

function StrategyTable({ candidates, columns, klineData, expandedKline, onKline, onBuy, emptyText }: {
  candidates: Candidate[];
  columns: Column[];
  klineData: Record<string, PriceBar[]>;
  expandedKline: string | null;
  onKline: (code: string) => void;
  onBuy: (c: Candidate) => void;
  emptyText: string;
}) {
  if (candidates.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p className="mb-3">{emptyText}</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">排名</th>
            {columns.map(col => (
              <th key={col.key} className={`px-3 py-2 text-${col.align === "right" ? "right" : col.align === "center" ? "center" : "left"} font-medium`}>{col.label}</th>
            ))}
            <th className="px-3 py-2 text-center font-medium">K线</th>
            <th className="px-3 py-2 text-center font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c, i) => (
            <>
              <tr key={c.code} className="border-t">
                <td className="px-3 py-2 text-center text-muted-foreground">{i + 1}</td>
                {columns.map(col => (
                  <td key={col.key} className={`px-3 py-2 text-${col.align === "right" ? "right" : col.align === "center" ? "center" : "left"}`}>{col.render(c)}</td>
                ))}
                <td className="px-3 py-2 text-center">
                  <button onClick={() => onKline(c.code)} className="p-1 text-muted-foreground hover:text-primary rounded" title="查看K线">
                    <CandleIcon className="h-4 w-4" />
                  </button>
                </td>
                <td className="px-3 py-2 text-center">
                  <button onClick={() => onBuy(c)} className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700">买入</button>
                </td>
              </tr>
              {expandedKline === c.code && klineData[c.code] && (
                <tr key={`${c.code}-kline`}>
                  <td colSpan={columns.length + 3} className="px-4 py-3 bg-muted/10">
                    <CandlestickChart data={klineData[c.code]} height={360} />
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DailyScan() {
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fibCandidates, setFibCandidates] = useState<Candidate[]>([]);
  const [v5Candidates, setV5Candidates] = useState<Candidate[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [scriptOutput, setScriptOutput] = useState<string | null>(null);
  const [noCache, setNoCache] = useState(false);
  const [klineData, setKlineData] = useState<Record<string, PriceBar[]>>({});
  const [expandedKline, setExpandedKline] = useState<string | null>(null);

  const fetchScanResults = async () => {
    try {
      const [fibData, v5Data] = await Promise.all([
        api.tools.get<any>("/scan-results?strategy=fibonacci"),
        api.tools.get<any>("/scan-results?strategy=v5"),
      ]);
      const fib = fibData?.candidates || [];
      const v5 = v5Data?.candidates || [];
      setFibCandidates(fib);
      setV5Candidates(v5);
      setNoCache(fib.length === 0 && v5.length === 0);
    } catch (e) {
      setNoCache(true);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const market = await api.tools.get<any>("/market/realtime");
      setMarket(market);
      await fetchScanResults();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateData = async () => {
    setUpdating(true);
    try {
      const json = await api.tools.post<any>("/update-data");
      if (json.ok) {
        alert(`数据更新完成: ${json.message}`);
      } else {
        alert(`更新失败: ${json.message || "未知错误"}`);
      }
    } catch (e: any) {
      alert(`更新失败: ${e.message}`);
    } finally {
      setUpdating(false);
    }
  };

  const handleBuy = async (code: string, name: string, strategy: string, extra: Record<string, any>) => {
    try {
      const data = await api.tools.post<any>(`/stock/${code}/buy`, { strategy, name, ...extra });
      alert(data.message);
    } catch (e: any) {
      alert(`买入失败: ${e.message}`);
    }
  };

  const fetchKline = async (code: string) => {
    if (klineData[code]) {
      setExpandedKline(expandedKline === code ? null : code);
      return;
    }
    try {
      const data = await api.tools.get<any>(`/stock/${code}`);
      const bars: PriceBar[] = (data.kline || []).reverse().map((r: any) => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume,
      }));
      setKlineData((prev) => ({ ...prev, [code]: bars }));
      setExpandedKline(code);
    } catch {}
  };

  const handleRunScan = async (script: string) => {
    setRunning(script);
    setScriptOutput("执行中...");
    try {
      const data = await api.tools.post<any>("/run-script", { script });
      const taskId = data.task_id;
      if (!taskId) {
        setScriptOutput("启动失败");
        setRunning(null);
        return;
      }
      const poll = async () => {
        const d = await api.tools.get<any>(`/run-script/${taskId}`);
        setScriptOutput(d.output || "");
        if (d.output && d.output.includes("执行中")) {
          setTimeout(poll, 3000);
        } else {
          setRunning(null);
          await fetchScanResults();
        }
      };
      setTimeout(poll, 3000);
    } catch (e: any) {
      setScriptOutput(`失败: ${e.message}`);
      setRunning(null);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const stats = market;
  const upRatio = stats && stats.total ? (stats.up / stats.total * 100).toFixed(1) : "0";
  const downRatio = stats && stats.total ? (stats.down / stats.total * 100).toFixed(1) : "0";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">每日选股</h1>
          <p className="text-sm text-muted-foreground mt-1">策略扫描与市场概览</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleUpdateData}
            disabled={updating}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Download className={`h-4 w-4 ${updating ? "animate-spin" : ""}`} />
            {updating ? "更新中..." : "更新数据"}
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

      {error && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Market Stats */}
      <div className="grid gap-4 md:grid-cols-5">
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">总数</div>
          <p className="text-xl font-bold">{stats?.total || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-red-500" />
            上涨
          </div>
          <p className="text-xl font-bold text-red-600">{stats?.up || 0}</p>
          <p className="text-xs text-muted-foreground">{upRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-green-500 rotate-180" />
            下跌
          </div>
          <p className="text-xl font-bold text-green-600">{stats?.down || 0}</p>
          <p className="text-xs text-muted-foreground">{downRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">涨停</div>
          <p className="text-xl font-bold text-red-600">{stats?.limit_up || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">跌停</div>
          <p className="text-xl font-bold text-green-600">{stats?.limit_down || 0}</p>
        </div>
      </div>

      {/* Market Breadth Bar */}
      {stats && stats.total > 0 && (
        <div className="border rounded-lg p-4 bg-card">
          <h2 className="font-semibold mb-3">市场宽度</h2>
          <div className="flex h-6 rounded-full overflow-hidden bg-muted">
            <div
              className="bg-red-500 transition-all"
              style={{ width: `${(stats.up / stats.total) * 100}%` }}
              title={`上涨 ${stats.up}`}
            />
            <div
              className="bg-gray-400 transition-all"
              style={{ width: `${((stats.flat || 0) / stats.total) * 100}%` }}
              title={`平盘 ${stats.flat || 0}`}
            />
            <div
              className="bg-green-500 transition-all"
              style={{ width: `${(stats.down / stats.total) * 100}%` }}
              title={`下跌 ${stats.down}`}
            />
          </div>
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span className="text-red-600">上涨 {stats.up}</span>
            <span>平盘 {stats.flat || 0}</span>
            <span className="text-green-600">下跌 {stats.down}</span>
          </div>
        </div>
      )}

      {/* 缓存为空时显示执行入口 */}
      {noCache && !running && !loading && (
        <div className="border rounded-lg p-8 bg-card">
          <h2 className="text-lg font-semibold mb-4 text-center">今日尚无选股结果</h2>
          <div className="grid gap-3 md:grid-cols-2 max-w-lg mx-auto">
            <button
              onClick={() => handleRunScan("fibonacci")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <Search className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">斐波那契选股</p>
                <p className="text-xs text-muted-foreground">约需1-2分钟</p>
              </div>
            </button>
            <button
              onClick={() => handleRunScan("v5")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <TrendingUp className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">趋势选股V5</p>
                <p className="text-xs text-muted-foreground">约需1-2分钟</p>
              </div>
            </button>
          </div>
        </div>
      )}

      {running && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
            <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
            <span className="font-semibold text-sm">
              {running === "fibonacci" ? "斐波那契" : "V5趋势"}选股执行中...
            </span>
          </div>
          <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-[400px] text-muted-foreground">
            {scriptOutput || "等待输出..."}
          </pre>
        </div>
      )}

      {/* 斐波那契选股结果 */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
          <h2 className="font-semibold">斐波那契选股结果 {fibCandidates.length > 0 ? `(${fibCandidates.length} 只)` : ""}</h2>
          <button
            onClick={() => handleRunScan("fibonacci")}
            disabled={running === "fibonacci"}
            className="flex items-center gap-1 px-3 py-1 text-xs border rounded-md hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${running === "fibonacci" ? "animate-spin" : ""}`} />
            重新选股
          </button>
        </div>
        <StrategyTable
          candidates={fibCandidates}
          columns={[
            { key: "code", label: "代码", render: c => <span className="font-mono">{c.code}</span> },
            { key: "name", label: "名称", render: c => c.name },
            { key: "price", label: "现价", align: "right", render: c => c.price.toFixed(2) },
            { key: "E", label: "E价", align: "right", render: c => c.E?.toFixed(2) ?? "-" },
            { key: "deviation", label: "偏差%", align: "right", render: c => <span className={(c.deviation ?? 0) >= 0 ? "text-red-600" : "text-green-600"}>{c.deviation?.toFixed(2) ?? "-"}%</span> },
            { key: "score", label: "评分", align: "right", render: c => <span className="font-medium">{c.score.toFixed(1)}</span> },
            { key: "swing", label: "摆动%", align: "right", render: c => `${c.swing?.toFixed(1) ?? "-"}%` },
            { key: "stop", label: "止损", align: "right", render: c => <span className="text-muted-foreground">{c.stop?.toFixed(2) ?? "-"}</span> },
            { key: "H_date", label: "H日期", align: "center", render: c => <span className="text-xs">{c.H_date}</span> },
            { key: "L_date", label: "L日期", align: "center", render: c => <span className="text-xs">{c.L_date}</span> },
          ]}
          klineData={klineData}
          expandedKline={expandedKline}
          onKline={fetchKline}
          onBuy={c => handleBuy(c.code, c.name, "fibonacci", { price: c.price, E: c.E, stop: c.stop, score: c.score })}
          emptyText="暂无斐波那契选股结果"
        />
      </div>

      {/* V5 选股结果 */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
          <h2 className="font-semibold">V5趋势选股结果 {v5Candidates.length > 0 ? `(${v5Candidates.length} 只)` : ""}</h2>
          <button
            onClick={() => handleRunScan("v5")}
            disabled={running === "v5"}
            className="flex items-center gap-1 px-3 py-1 text-xs border rounded-md hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${running === "v5" ? "animate-spin" : ""}`} />
            重新选股
          </button>
        </div>
        <StrategyTable
          candidates={v5Candidates}
          columns={[
            { key: "code", label: "代码", render: c => <span className="font-mono">{c.code}</span> },
            { key: "name", label: "名称", render: c => c.name },
            { key: "price", label: "现价", align: "right", render: c => c.price.toFixed(2) },
            { key: "score", label: "评分", align: "right", render: c => <span className="font-medium">{c.score.toFixed(1)}</span> },
          ]}
          klineData={klineData}
          expandedKline={expandedKline}
          onKline={fetchKline}
          onBuy={c => handleBuy(c.code, c.name, "v5", { price: c.price, score: c.score })}
          emptyText="暂无V5趋势选股结果"
        />
      </div>
    </div>
  );
}

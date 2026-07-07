import { useEffect, useState } from "react";
import { Search, RefreshCw, TrendingUp, Download, CandlestickChart as CandleIcon } from "lucide-react";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
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
  E: number;
  score: number;
  deviation: number;
  H: number;
  L: number;
  H_date: string;
  L_date: string;
  swing: number;
  stop: number;
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
      const [fibRes, v5Res] = await Promise.all([
        fetch("/tools/scan-results?strategy=fibonacci"),
        fetch("/tools/scan-results?strategy=v5"),
      ]);
      console.log("fibRes status:", fibRes.status);
      const fibData = fibRes.ok ? await fibRes.json() : null;
      const v5Data = v5Res.ok ? await v5Res.json() : null;
      console.log("fibData:", fibData);
      const fib = fibData?.candidates || [];
      const v5 = v5Data?.candidates || [];
      console.log("fib candidates:", fib.length);
      setFibCandidates(fib);
      setV5Candidates(v5);
      setNoCache(fib.length === 0 && v5.length === 0);
    } catch (e) {
      console.error("fetchScanResults error:", e);
      setNoCache(true);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [mktRes] = await Promise.all([
        fetch("/tools/market/realtime"),
      ]);
      if (!mktRes.ok) throw new Error("Failed to load market data");
      setMarket(await mktRes.json());
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
      const res = await fetch("/tools/update-data", { method: "POST" });
      const json = await res.json();
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
      const res = await fetch(`/tools/stock/${code}/buy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy, name, ...extra }),
      });
      const data = await res.json();
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
      const res = await fetch(`/tools/stock/${code}`);
      if (res.ok) {
        const data = await res.json();
        const bars: PriceBar[] = (data.kline || []).reverse().map((r: any) => ({
          time: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume,
        }));
        setKlineData((prev) => ({ ...prev, [code]: bars }));
        setExpandedKline(code);
      }
    } catch {}
  };

  const handleRunScan = async (script: string) => {
    setRunning(script);
    setScriptOutput("执行中...");
    try {
      const res = await fetch("/tools/run-script", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
      });
      const data = await res.json();
      const taskId = data.task_id;
      if (!taskId) {
        setScriptOutput("启动失败");
        setRunning(null);
        return;
      }
      const poll = async () => {
        const r = await fetch(`/tools/run-script/${taskId}`);
        const d = await r.json();
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
        {fibCandidates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">E价</th>
                  <th className="px-3 py-2 text-right font-medium">偏差%</th>
                  <th className="px-3 py-2 text-right font-medium">评分</th>
                  <th className="px-3 py-2 text-right font-medium">摆动%</th>
                  <th className="px-3 py-2 text-right font-medium">止损</th>
                  <th className="px-3 py-2 text-center font-medium">H日期</th>
                  <th className="px-3 py-2 text-center font-medium">L日期</th>
                  <th className="px-3 py-2 text-center font-medium">K线</th>
                  <th className="px-3 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {fibCandidates.map((c, i) => (
                  <>
                    <tr key={c.code} className="border-t">
                      <td className="px-3 py-2 text-center text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{c.code}</td>
                      <td className="px-3 py-2">{c.name}</td>
                      <td className="px-3 py-2 text-right">{c.price.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right">{c.E.toFixed(2)}</td>
                      <td className={`px-3 py-2 text-right ${c.deviation >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {c.deviation.toFixed(2)}%
                      </td>
                      <td className="px-3 py-2 text-right font-medium">{c.score.toFixed(1)}</td>
                      <td className="px-3 py-2 text-right">{c.swing.toFixed(1)}%</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{c.stop.toFixed(2)}</td>
                      <td className="px-3 py-2 text-center text-xs">{c.H_date}</td>
                      <td className="px-3 py-2 text-center text-xs">{c.L_date}</td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => fetchKline(c.code)}
                          className="p-1 text-muted-foreground hover:text-primary rounded"
                          title="查看K线"
                        >
                          <CandleIcon className="h-4 w-4" />
                        </button>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button
                          onClick={() => handleBuy(c.code, c.name, "fibonacci", {
                            price: c.price, E: c.E, stop: c.stop, score: c.score,
                          })}
                          className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                        >
                          买入
                        </button>
                      </td>
                    </tr>
                    {expandedKline === c.code && klineData[c.code] && (
                      <tr key={`${c.code}-kline`}>
                        <td colSpan={13} className="px-4 py-3 bg-muted/10">
                          <CandlestickChart data={klineData[c.code]} height={360} />
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 text-center text-muted-foreground">
            <p className="mb-3">暂无斐波那契选股结果</p>
          </div>
        )}
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
        {v5Candidates.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">评分</th>
                  <th className="px-3 py-2 text-center font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {v5Candidates.map((c, i) => (
                  <tr key={c.code} className="border-t">
                    <td className="px-3 py-2 text-center text-muted-foreground">{i + 1}</td>
                    <td className="px-3 py-2 font-mono">{c.code}</td>
                    <td className="px-3 py-2">{c.name}</td>
                    <td className="px-3 py-2 text-right">{c.price.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-medium">{c.score.toFixed(1)}</td>
                    <td className="px-3 py-2 text-center">
                      <button
                        onClick={() => handleBuy(c.code, c.name, "v5", {
                          price: c.price, score: c.score,
                        })}
                        className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                      >
                        买入
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 text-center text-muted-foreground">
            <p className="mb-3">暂无V5趋势选股结果</p>
            {!running && (
              <button
                onClick={() => handleRunScan("v5")}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90"
              >
                开始V5选股
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

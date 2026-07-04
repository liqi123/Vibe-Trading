import { useEffect, useState } from "react";
import { Search, RefreshCw, TrendingUp, Filter, Download } from "lucide-react";

interface MarketStats {
  total: number;
  up: number;
  down: number;
  flat: number;
  limit_up: number;
  limit_down: number;
}

export function DailyScan() {
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningScript, setRunningScript] = useState<string | null>(null);
  const [scriptOutput, setScriptOutput] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/tools/market/realtime");
      if (!res.ok) throw new Error("Failed to load market data");
      setMarket(await res.json());
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

  useEffect(() => { fetchData(); }, []);

  const handleRunScript = async (script: string) => {
    setRunningScript(script);
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
        setRunningScript(null);
        return;
      }
      // Poll for output
      const poll = async () => {
        try {
          const r = await fetch(`/tools/run-script/${taskId}`);
          const d = await r.json();
          setScriptOutput(d.output || "无输出");
          // Check if still running (output ends with "执行中...")
          if (d.output && d.output.includes("执行中")) {
            setTimeout(poll, 3000);
          } else {
            setRunningScript(null);
          }
        } catch {
          setRunningScript(null);
        }
      };
      setTimeout(poll, 3000);
    } catch (e: any) {
      setScriptOutput(`启动失败: ${e.message}`);
      setRunningScript(null);
    }
  };

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

      {/* Quick Actions */}
      <div className="border rounded-lg p-4 bg-card">
        <h2 className="font-semibold mb-3">快速操作</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <button
            onClick={() => handleRunScript("fibonacci")}
            disabled={runningScript === "fibonacci"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <Search className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "fibonacci" ? "执行中..." : "斐波那契选股"}</p>
            </div>
          </button>
          <button
            onClick={() => handleRunScript("v5")}
            disabled={runningScript === "v5"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <Filter className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "v5" ? "执行中..." : "趋势选股V5"}</p>
            </div>
          </button>
          <button
            onClick={() => handleRunScript("stops")}
            disabled={runningScript === "stops"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <TrendingUp className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "stops" ? "执行中..." : "止损检查"}</p>
            </div>
          </button>
        </div>
      </div>

      {/* Script Output */}
      {scriptOutput && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <h2 className="font-semibold">执行结果</h2>
            <button onClick={() => setScriptOutput(null)} className="text-xs text-muted-foreground hover:text-foreground">关闭</button>
          </div>
          <pre className="p-4 text-xs overflow-auto max-h-[500px] whitespace-pre-wrap font-mono">{scriptOutput}</pre>
        </div>
      )}
    </div>
  );
}

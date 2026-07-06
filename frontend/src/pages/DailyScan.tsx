import { useEffect, useRef, useState } from "react";
import { Search, RefreshCw, TrendingUp, Filter, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";

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
  const pollCancelledRef = useRef(false);
  const { t } = useTranslation();

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api.tools.get<any>("/market/realtime");
      setMarket(d);
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
        console.log(`数据更新完成: ${json.message}`);
      } else {
        console.log(`更新失败: ${json.message || "未知错误"}`);
      }
    } catch (e: any) {
      console.log(`更新失败: ${e.message}`);
    } finally {
      setUpdating(false);
    }
  };

  useEffect(() => { fetchData(); }, []);
  useEffect(() => { return () => { pollCancelledRef.current = true; }; }, []);

  const handleRunScript = async (script: string) => {
    setRunningScript(script);
      setScriptOutput(t("dailyScan.executing"));
    try {
      const data = await api.tools.post<any>("/run-script", { script });
      const taskId = data.task_id;
      if (!taskId) {
        setScriptOutput(t("dailyScan.startFailed"));
        setRunningScript(null);
        return;
      }
      // Poll for output
      const poll = async () => {
        if (pollCancelledRef.current) return;
        try {
          const d = await api.tools.get<any>(`/run-script/${taskId}`);
          if (pollCancelledRef.current) return;
          setScriptOutput(d.output || t("dailyScan.noOutput"));
          if (d.output && d.output.includes("执行中")) {
            if (!pollCancelledRef.current) setTimeout(poll, 3000);
          } else {
            setRunningScript(null);
          }
        } catch (e) {
          console.error('Poll failed:', e);
          setRunningScript(null);
        }
      };
      setTimeout(poll, 3000);
    } catch (e: any) {
      setScriptOutput(`${t("dailyScan.startFailed")}: ${e.message}`);
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
          <h1 className="text-2xl font-bold">{t("dailyScan.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("dailyScan.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleUpdateData}
            disabled={updating}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Download className={`h-4 w-4 ${updating ? "animate-spin" : ""}`} />
            {updating ? t("dailyScan.updating") : t("dailyScan.updateData")}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t("dailyScan.refresh")}
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
          <div className="text-sm text-muted-foreground mb-1">{t("dailyScan.total")}</div>
          <p className="text-xl font-bold">{stats?.total || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-red-500" />
            {t("dailyScan.up")}
          </div>
          <p className="text-xl font-bold text-red-600">{stats?.up || 0}</p>
          <p className="text-xs text-muted-foreground">{upRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-green-500 rotate-180" />
            {t("dailyScan.down")}
          </div>
          <p className="text-xl font-bold text-green-600">{stats?.down || 0}</p>
          <p className="text-xs text-muted-foreground">{downRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("dailyScan.limitUp")}</div>
          <p className="text-xl font-bold text-red-600">{stats?.limit_up || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">{t("dailyScan.limitDown")}</div>
          <p className="text-xl font-bold text-green-600">{stats?.limit_down || 0}</p>
        </div>
      </div>

      {/* Market Breadth Bar */}
      {stats && stats.total > 0 && (
        <div className="border rounded-lg p-4 bg-card">
          <h2 className="font-semibold mb-3">{t("dailyScan.marketBreadth")}</h2>
          <div className="flex h-6 rounded-full overflow-hidden bg-muted">
            <div
              className="bg-red-500 transition-all"
              style={{ width: `${(stats.up / stats.total) * 100}%` }}
              title={`${t("dailyScan.up")} ${stats.up}`}
            />
            <div
              className="bg-gray-400 transition-all"
              style={{ width: `${((stats.flat || 0) / stats.total) * 100}%` }}
              title={`${t("dailyScan.flat")} ${stats.flat || 0}`}
            />
            <div
              className="bg-green-500 transition-all"
              style={{ width: `${(stats.down / stats.total) * 100}%` }}
              title={`${t("dailyScan.down")} ${stats.down}`}
            />
          </div>
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span className="text-red-600">{t("dailyScan.up")} {stats.up}</span>
            <span>{t("dailyScan.flat")} {stats.flat || 0}</span>
            <span className="text-green-600">{t("dailyScan.down")} {stats.down}</span>
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="border rounded-lg p-4 bg-card">
        <h2 className="font-semibold mb-3">{t("dailyScan.quickActions")}</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <button
            onClick={() => handleRunScript("fibonacci")}
            disabled={runningScript === "fibonacci"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <Search className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "fibonacci" ? t("dailyScan.executing") : t("dailyScan.fibonacciScan")}</p>
            </div>
          </button>
          <button
            onClick={() => handleRunScript("v5")}
            disabled={runningScript === "v5"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <Filter className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "v5" ? t("dailyScan.executing") : t("dailyScan.v5TrendScan")}</p>
            </div>
          </button>
          <button
            onClick={() => handleRunScript("stops")}
            disabled={runningScript === "stops"}
            className="flex items-center gap-3 p-3 border rounded-lg hover:bg-muted transition-colors text-left"
          >
            <TrendingUp className="h-5 w-5 text-primary" />
            <div>
              <p className="font-medium text-sm">{runningScript === "stops" ? t("dailyScan.executing") : t("dailyScan.stopCheck")}</p>
            </div>
          </button>
        </div>
      </div>

      {/* Script Output */}
      {scriptOutput && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <h2 className="font-semibold">{t("dailyScan.scriptOutput")}</h2>
            <button onClick={() => setScriptOutput(null)} className="text-xs text-muted-foreground hover:text-foreground">{t("dailyScan.close")}</button>
          </div>
          <pre className="p-4 text-xs overflow-auto max-h-[500px] whitespace-pre-wrap font-mono">{scriptOutput}</pre>
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { Search, TrendingUp, TrendingDown, Minus, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

interface SwingPoint {
  date: string;
  type: string;
  price: number;
}

interface Signal {
  date: string;
  type: string;
  direction?: string;
  level?: number;
  top?: number;
  bottom?: number;
}

interface SmcResult {
  code: string;
  name: string;
  swing_points: SwingPoint[];
  signals: Signal[];
  raw_output: string;
  error?: string;
}

function signalIcon(type: string, dir?: string) {
  if (type === "BOS") {
    return dir === "多" ? <TrendingUp className="h-4 w-4 text-green-500" /> : <TrendingDown className="h-4 w-4 text-red-500" />;
  }
  if (type === "ChoCH") {
    return dir === "多" ? <TrendingUp className="h-4 w-4 text-green-600" /> : <TrendingDown className="h-4 w-4 text-red-600" />;
  }
  if (type === "FVG") {
    return dir === "bullish" ? <TrendingUp className="h-4 w-4 text-blue-400" /> : <TrendingDown className="h-4 w-4 text-orange-400" />;
  }
  return <Minus className="h-4 w-4 text-muted-foreground" />;
}

export function SmcAnalysis() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<SmcResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"swings" | "signals" | "raw">("swings");

  const handleSearch = async () => {
    const q = code.trim().toLowerCase();
    if (!q) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.tools.get<any>(`/smc/${encodeURIComponent(q)}`);
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">SMC 结构分析</h1>
        <p className="text-sm text-muted-foreground mt-1">Smart Money Concepts — Swing/BOS/ChoCH/FVG 机构足迹分析</p>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="股票代码，如 603163 或 sh600519"
            className="w-full pl-10 pr-4 py-2 border rounded-md bg-background text-sm"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "分析中..." : "分析"}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-md text-sm">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-semibold">
              {result.code} {result.name}
            </h2>
          </div>

          <div className="flex gap-1 border-b">
            {(["swings", "signals", "raw"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  tab === t
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t === "swings" ? "Swing 高低点" : t === "signals" ? "结构信号" : "原始输出"}
              </button>
            ))}
          </div>

          {tab === "swings" && (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">日期</th>
                    <th className="text-left px-4 py-2 font-medium">类型</th>
                    <th className="text-right px-4 py-2 font-medium">价格</th>
                  </tr>
                </thead>
                <tbody>
                  {result.swing_points.map((sp, i) => (
                    <tr key={i} className="border-t hover:bg-muted/30">
                      <td className="px-4 py-2">{sp.date}</td>
                      <td className="px-4 py-2">
                        <span className={`inline-flex items-center gap-1 ${
                          sp.type === "高" ? "text-red-500" : "text-green-500"
                        }`}>
                          {sp.type === "高" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                          Swing{sp.type}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono">{sp.price.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "signals" && (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">日期</th>
                    <th className="text-left px-4 py-2 font-medium">信号</th>
                    <th className="text-right px-4 py-2 font-medium">价位</th>
                  </tr>
                </thead>
                <tbody>
                  {result.signals.map((sig, i) => (
                    <tr key={i} className="border-t hover:bg-muted/30">
                      <td className="px-4 py-2">{sig.date}</td>
                      <td className="px-4 py-2">
                        <span className="inline-flex items-center gap-1">
                          {signalIcon(sig.type, sig.direction)}
                          {sig.type}
                          {sig.direction && `(${sig.direction})`}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {sig.level !== undefined ? sig.level.toFixed(2) :
                         sig.top !== undefined ? `${sig.bottom?.toFixed(2)}~${sig.top.toFixed(2)}` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "raw" && (
            <pre className="text-xs font-mono whitespace-pre-wrap bg-muted/30 p-4 rounded-md max-h-[600px] overflow-auto">
              {result.raw_output}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import { Search, RefreshCw, TrendingUp, TrendingDown, Target, BarChart3, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

interface Indicator {
  ma5: number; ma10: number; ma20: number; ma60: number;
  rsi14: number; avg_vol_5: number; avg_vol_20: number;
}

interface Cycle {
  h_date: string; h_price: number; l_date: string; l_price: number;
  E: number; swing_pct: number; days: number; deviation: number; qualifies: boolean;
}

interface KlineBar {
  date: string; open: number; high: number; low: number; close: number; volume: number;
}

interface AnalysisResult {
  code: string; name: string; current_price: number;
  E: number; X: number; runaway: number; exit_price: number;
  window_high: number; window_low: number;
  window_high_date: string; window_low_date: string;
  indicators: Indicator; cycles: Cycle[]; valid_cycles: Cycle[];
  vol_ratio: number; kline: KlineBar[];
  error?: string;
}

function pnlClass(v: number) {
  if (v > 0) return "text-red-600";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

export function StockAnalysis() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "cycles" | "kline">("overview");

  const handleSearch = async () => {
    const q = code.trim().toLowerCase();
    if (!q) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.tools.get<any>(`/stock-analysis/${encodeURIComponent(q)}`);
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

  const eClass = (price: number, E: number) => {
    if (!E) return "text-muted-foreground";
    if (price >= E) return "text-green-600 font-bold";
    return "text-red-600 font-bold";
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">个股深度分析</h1>
        <p className="text-sm text-muted-foreground mt-1">斐波那契价位、技术指标、摆动周期分析</p>
      </div>

      {/* Search Bar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
            placeholder="输入股票代码，如 sh600519 或 000725"
            className="w-full border rounded-md pl-9 pr-3 py-2 text-sm bg-background"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading || !code.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
        >
          {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          分析
        </button>
      </div>

      {error && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-700 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Key Metrics Cards */}
          <div className="grid gap-4 grid-cols-2 md:grid-cols-4 lg:grid-cols-5">
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">现价</div>
              <p className={`text-xl font-bold ${pnlClass(result.current_price - result.E)}`}>
                {result.current_price.toFixed(2)}
              </p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">E价（买入参考）</div>
              <p className={`text-xl font-bold ${eClass(result.current_price, result.E)}`}>
                {result.E?.toFixed(2) || "-"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                H={result.window_high.toFixed(2)} ({result.window_high_date})
              </p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">X价（卖出参考）</div>
              <p className="text-xl font-bold text-blue-600">{result.X?.toFixed(2) || "-"}</p>
              <p className="text-xs text-muted-foreground mt-1">
                L={result.window_low.toFixed(2)} ({result.window_low_date})
              </p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">跑路价</div>
              <p className="text-xl font-bold text-orange-600">{result.runaway?.toFixed(2) || "-"}</p>
              <p className="text-xs text-muted-foreground mt-1">出货价: {result.exit_price?.toFixed(2)}</p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                <Target className="h-4 w-4" />
                偏差
              </div>
              <p className={`text-xl font-bold ${result.E ? (result.current_price >= result.E ? "text-green-600" : "text-red-600") : ""}`}>
                {result.E ? `${((result.current_price - result.E) / result.E * 100).toFixed(1)}%` : "-"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {result.current_price >= result.E ? "≥ E价 ✓" : "< E价"}
              </p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center gap-1 border-b">
            {[
              { key: "overview" as const, label: "概览", icon: BarChart3 },
              { key: "cycles" as const, label: `摆动周期 (${result.cycles.length})`, icon: TrendingUp },
              { key: "kline" as const, label: "K线数据", icon: TrendingDown },
            ].map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2 text-sm border-b-2 transition-colors ${
                  tab === key
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </div>

          {tab === "overview" && (
            <div className="grid gap-6 md:grid-cols-2">
              {/* Indicators */}
              <div className="border rounded-lg p-4 bg-card">
                <h2 className="font-semibold mb-3">技术指标</h2>
                <div className="space-y-2 text-sm">
                  {[
                    { label: "MA5", value: result.indicators.ma5 },
                    { label: "MA10", value: result.indicators.ma10 },
                    { label: "MA20", value: result.indicators.ma20 },
                    { label: "MA60", value: result.indicators.ma60 },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between py-1 border-b last:border-0">
                      <span className="text-muted-foreground">{label}</span>
                      <span className={`font-mono font-medium ${value && result.current_price >= value ? "text-green-600" : "text-red-600"}`}>
                        {value?.toFixed(2) || "-"}
                      </span>
                    </div>
                  ))}
                  <div className="flex items-center justify-between py-1 border-b">
                    <span className="text-muted-foreground">RSI(14)</span>
                    <span className={`font-mono font-medium ${result.indicators.rsi14 ? (result.indicators.rsi14 > 70 ? "text-red-600" : result.indicators.rsi14 < 30 ? "text-green-600" : "") : ""}`}>
                      {result.indicators.rsi14?.toFixed(1) || "-"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b">
                    <span className="text-muted-foreground">量比 (vs 20日均量)</span>
                    <span className={`font-mono font-medium ${result.vol_ratio > 1.5 ? "text-red-600" : ""}`}>
                      {result.vol_ratio?.toFixed(2) || "-"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-1">
                    <span className="text-muted-foreground">摆动幅度</span>
                    <span className="font-mono font-medium">
                      {((result.window_high - result.window_low) / result.window_low * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Valid Cycles Summary */}
              <div className="border rounded-lg p-4 bg-card">
                <h2 className="font-semibold mb-3">有效周期</h2>
                {result.valid_cycles.length > 0 ? (
                  <div className="space-y-2">
                    {result.valid_cycles.slice(0, 5).map((c, i) => (
                      <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b last:border-0">
                        <div>
                          <span className="text-muted-foreground">L:</span> {c.l_date}
                          <span className="text-muted-foreground ml-2">H:</span> {c.h_date}
                        </div>
                        <div>
                          <span className="font-mono">{c.E.toFixed(2)}</span>
                          <span className="text-muted-foreground ml-1">偏差 {c.deviation.toFixed(1)}%</span>
                        </div>
                      </div>
                    ))}
                    <p className="text-xs text-muted-foreground pt-1">
                      共 {result.valid_cycles.length} 个有效周期
                    </p>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">当前价位无符合条件的周期</p>
                )}
              </div>
            </div>
          )}

          {tab === "cycles" && (
            <div className="border rounded-lg bg-card overflow-hidden">
              <div className="px-4 py-3 border-b bg-muted/30">
                <h2 className="font-semibold">所有摆动周期</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">H日期</th>
                      <th className="px-3 py-2 text-right font-medium">H价</th>
                      <th className="px-3 py-2 text-left font-medium">L日期</th>
                      <th className="px-3 py-2 text-right font-medium">L价</th>
                      <th className="px-3 py-2 text-right font-medium">E价</th>
                      <th className="px-3 py-2 text-right font-medium">波动%</th>
                      <th className="px-3 py-2 text-right font-medium">天数</th>
                      <th className="px-3 py-2 text-right font-medium">偏差%</th>
                      <th className="px-3 py-2 text-center font-medium">可用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.cycles.map((c, i) => (
                      <tr key={i} className={`border-t hover:bg-muted/30 ${c.qualifies ? "bg-green-50/30" : ""}`}>
                        <td className="px-3 py-2">{c.h_date}</td>
                        <td className="px-3 py-2 text-right font-mono">{c.h_price.toFixed(2)}</td>
                        <td className="px-3 py-2">{c.l_date}</td>
                        <td className="px-3 py-2 text-right font-mono">{c.l_price.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right font-mono font-medium">{c.E.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right">{c.swing_pct.toFixed(1)}%</td>
                        <td className="px-3 py-2 text-right text-muted-foreground">{c.days}</td>
                        <td className={`px-3 py-2 text-right font-medium ${c.deviation <= 2.5 ? "text-green-600" : ""}`}>
                          {c.deviation.toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 text-center">
                          {c.qualifies ? (
                            <span className="text-green-600 font-bold text-xs bg-green-100 px-1.5 py-0.5 rounded">✓</span>
                          ) : (
                            <span className="text-muted-foreground text-xs">-</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {result.cycles.length === 0 && (
                      <tr>
                        <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">未找到有效摆动周期</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === "kline" && (
            <div className="border rounded-lg bg-card overflow-hidden">
              <div className="px-4 py-3 border-b bg-muted/30">
                <h2 className="font-semibold">K线数据（近60个交易日）</h2>
              </div>
              <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground sticky top-0">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">日期</th>
                      <th className="px-3 py-2 text-right font-medium">开盘</th>
                      <th className="px-3 py-2 text-right font-medium">最高</th>
                      <th className="px-3 py-2 text-right font-medium">最低</th>
                      <th className="px-3 py-2 text-right font-medium">收盘</th>
                      <th className="px-3 py-2 text-right font-medium">成交量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.kline.map((k, i) => (
                      <tr key={i} className="border-t hover:bg-muted/30 font-mono">
                        <td className="px-3 py-1.5">{k.date}</td>
                        <td className={`px-3 py-1.5 text-right ${k.close >= k.open ? "text-red-600" : "text-green-600"}`}>{k.open.toFixed(2)}</td>
                        <td className={`px-3 py-1.5 text-right ${k.close >= k.open ? "text-red-600" : "text-green-600"}`}>{k.high.toFixed(2)}</td>
                        <td className={`px-3 py-1.5 text-right ${k.close >= k.open ? "text-red-600" : "text-green-600"}`}>{k.low.toFixed(2)}</td>
                        <td className={`px-3 py-1.5 text-right font-bold ${k.close >= k.open ? "text-red-600" : "text-green-600"}`}>{k.close.toFixed(2)}</td>
                        <td className="px-3 py-1.5 text-right text-muted-foreground">{k.volume.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {!result && !loading && !error && (
        <div className="border rounded-lg p-12 bg-card">
          <div className="text-center text-muted-foreground">
            <Search className="h-12 w-12 mx-auto mb-4 opacity-30" />
            <p>输入股票代码开始分析</p>
            <p className="text-sm mt-1">支持 sh600519 / sz000001 / 600519 格式</p>
          </div>
        </div>
      )}
    </div>
  );
}

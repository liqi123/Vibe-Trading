import { useState, useEffect } from "react";
import { Search, AlertTriangle, RefreshCw, ScanLine, BookOpen, Target } from "lucide-react";
import { api } from "@/lib/api";
import { CzscChart, type CzscBi, type CzscZS, type CzscKline, type CzscBuyPoint } from "@/components/charts/CzscChart";

interface CzscBiRes extends CzscBi {}
interface CzscZSRes extends CzscZS {}
interface CzscKlineRes extends CzscKline {}

interface BuyPointInfo {
  buy_points: string[];
  buy_point_marks?: { label: string; date: string; price: number; kind: string; live?: boolean }[];
  bi_count: number;
  zs_count: number;
  last_bi_dir: "up" | "down" | "" | null;
  in_zs: boolean;
  zs_range: [number, number] | null;
}

interface CzscAnalysisResult {
  ok: boolean;
  code?: string;
  detail?: string;
  klines?: CzscKlineRes[];
  bis?: CzscBiRes[];
  zs_list?: CzscZSRes[];
  signals?: { k1?: string; k2?: string; k3?: string; k4?: string; k5?: string; score?: string }[];
  buy_point_info?: BuyPointInfo;
  score?: number;
  analysis?: {
    date: string;
    price: number;
    bi_count: number;
    zs_count: number;
    last_bi_dir: "up" | "down" | "" | null;
    points: string[];
    suggestion: string;
  };
  elapsed_ms?: number;
}

interface ScanPick {
  code: string;
  name: string;
  price: number;
  score: number;
  buy_points: string[];
  buy_point?: string | null;
  last_bi_dir: "up" | "down" | "" | null;
  bi_count: number;
  zs_count: number;
  in_zs: boolean;
  zs_range: [number, number] | null;
  safe_to_buy?: boolean;
  zg?: number;
  safe_price_max?: number;
}

type TabKey = "chart" | "bis" | "zs" | "signals" | "scan";

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-600";
  if (score >= 60) return "text-blue-600";
  if (score >= 40) return "text-yellow-600";
  return "text-muted-foreground";
}

function scoreBg(score: number): string {
  if (score >= 80) return "bg-green-500/15 text-green-700 border-green-500/30";
  if (score >= 60) return "bg-blue-500/15 text-blue-700 border-blue-500/30";
  if (score >= 40) return "bg-yellow-500/15 text-yellow-700 border-yellow-500/30";
  return "bg-gray-500/15 text-muted-foreground border-gray-500/30";
}

export function CzscAnalysis() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<CzscAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("chart");

  // 选股扫描
  const [scanResult, setScanResult] = useState<{ picks: ScanPick[]; total: number; scanned: number; elapsed_ms: number } | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  // 页面首次加载: 默认进入选股扫描 tab（扫描需用户主动点击，全市场扫描 1~3 分钟）
  useEffect(() => {
    setTab("scan");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = async (overrideCode?: string) => {
    const q = (overrideCode ?? code).trim().toLowerCase();
    if (!q) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = (await api.tools.get<any>(
        `/czsc/${encodeURIComponent(q)}?with_signals=true&limit=300`,
      )) as CzscAnalysisResult;
      if (data && !data.ok) {
        setError((data as any).detail || "分析失败");
      } else {
        setResult(data);
        setTab("chart");
      }
    } catch (e: any) {
      setError(e.message || "请求失败");
    } finally {
      setLoading(false);
    }
  };

  // 点击扫描结果行: 填入 code → 搜索 → 跳到图表 tab
  const handlePickClick = async (p: ScanPick) => {
    setCode(p.code);
    await handleSearch(p.code);
    // 滚动回页面顶部，方便看图
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleScan = async () => {
    setScanLoading(true);
    setScanError(null);
    try {
      const data = (await api.tools.post<any>("/czsc/scan", {
        min_score: 50,
        with_buy_point: true,
        use_cache: true,
      })) as any;
      if (data && !data.ok) {
        setScanError((data as any).detail || "扫描失败");
      } else {
        setScanResult({
          picks: data.picks || [],
          total: data.total || 0,
          scanned: data.scanned || 0,
          elapsed_ms: data.elapsed_ms || 0,
        });
      }
    } catch (e: any) {
      setScanError(e.message || "扫描失败");
    } finally {
      setScanLoading(false);
    }
  };

  // 图表买卖点: 优先用后端真实坐标 (落在真实摆动位), 否则回退旧逻辑
  const chartBuyPoints: CzscBuyPoint[] = (() => {
    const marks = result?.buy_point_info?.buy_point_marks;
    if (marks && marks.length > 0) {
      return marks.map((m) => ({ date: m.date, type: m.label, price: m.price, live: m.live }));
    }
    if (!result?.bis || !result.buy_point_info?.buy_points) return [];
    const pts: CzscBuyPoint[] = [];
    const lastBi = result.bis[result.bis.length - 1];
    const buyTypes = result.buy_point_info.buy_points;
    if (lastBi && buyTypes.length > 0) {
      for (const t of buyTypes) {
        const isBuy = /买/.test(t);
        const price = isBuy ? lastBi.low : lastBi.high;
        pts.push({
          date: lastBi.edt,
          type: t,
          price,
        });
      }
    }
    return pts;
  })();

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold">缠论结构分析</h1>
          <p className="text-sm text-muted-foreground mt-1">
            基于 czsc（Rust + PyO3）识别分型/笔/中枢/买卖点，222 个信号函数全接入
          </p>
        </div>
        <button
          onClick={() => { setTab("scan"); if (!scanResult) handleScan(); }}
          disabled={scanLoading}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          <ScanLine className="h-4 w-4" />
          {scanLoading ? "选股扫描中..." : "缠论选股扫描"}
        </button>
      </div>

      {/* 搜索栏 */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="股票代码，如 sz000001 或 600519"
            className="w-full pl-10 pr-4 py-2 border rounded-md bg-background text-sm"
          />
        </div>
        <button
          onClick={() => handleSearch()}
          disabled={loading}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-2"
        >
          {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          {loading ? "分析中..." : "分析"}
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-md text-sm">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}
      {scanError && tab === "scan" && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-md text-sm">
          <AlertTriangle className="h-4 w-4" />
          选股扫描失败: {scanError}
        </div>
      )}

      {/* Tabs */}
      {(result || tab === "scan") && (
        <div className="flex gap-1 border-b flex-wrap">
          {(
            [
              ["chart", "缠论结构图"],
              ["bis", "笔列表"],
              ["zs", "中枢列表"],
              ["signals", "信号列表"],
              ["scan", "选股扫描"],
            ] as [TabKey, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === k
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* Tab: 选股扫描 */}
      {tab === "scan" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <p className="text-sm text-muted-foreground">
              扫描市场近5日日均额≥5000万的股票，筛选缠论评分≥50且具备买点候选
              <span className="ml-2 text-primary">· 点击行查看缠论结构图</span>
            </p>
            <button
              onClick={handleScan}
              disabled={scanLoading}
              className="inline-flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${scanLoading ? "animate-spin" : ""}`} />
              {scanLoading ? "扫描中..." : (scanResult ? "重新扫描" : "开始扫描")}
            </button>
          </div>
          {!scanResult && !scanLoading && (
            <div className="p-8 text-center text-muted-foreground border rounded-lg">
              点击右上角「开始扫描」按钮启动选股（全市场扫描约 1~3 分钟）
            </div>
          )}
          {scanLoading && !scanResult && (
            <div className="p-8 text-center text-muted-foreground border rounded-lg">
              首次全市场扫描约 1~3 分钟，请耐心等待...
            </div>
          )}
          {scanResult && (
            <div className="border rounded-lg overflow-hidden">
              <div className="px-4 py-3 bg-muted/40 text-xs text-muted-foreground flex flex-wrap gap-4">
                <span>候选股: <strong className="text-foreground">{scanResult.total}</strong></span>
                <span>扫描总数: <strong className="text-foreground">{scanResult.scanned}</strong></span>
                <span>耗时: <strong className="text-foreground">{(scanResult.elapsed_ms / 1000).toFixed(1)}s</strong></span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium">代码</th>
                      <th className="px-4 py-2 text-left font-medium">名称</th>
                      <th className="px-4 py-2 text-right font-medium">现价</th>
                      <th className="px-4 py-2 text-center font-medium">评分</th>
                      <th className="px-4 py-2 text-left font-medium">买点</th>
                      <th className="px-4 py-2 text-center font-medium">笔方向</th>
                      <th className="px-4 py-2 text-center font-medium">笔/中枢</th>
                      <th className="px-4 py-2 text-center font-medium">中枢位置</th>
                      <th className="px-4 py-2 text-center font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanResult.picks.length === 0 && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                          暂无符合条件的股票
                        </td>
                      </tr>
                    )}
                    {scanResult.picks.map((p) => {
                      const isHighRisk = p.safe_to_buy === false && !!p.zg;
                      return (
                        <tr
                          key={p.code}
                          onClick={() => handlePickClick(p)}
                          className={`border-t hover:bg-primary/5 hover:cursor-pointer transition-colors ${isHighRisk ? "bg-amber-50/40" : ""}`}
                          title={`点击查看 ${p.name} (${p.code}) 缠论结构图`}
                        >
                          <td className="px-4 py-2 font-mono">
                            {isHighRisk && <span title="高位脱离中枢安全区" className="mr-1 inline-block w-2 h-2 rounded-full bg-amber-500 align-middle"></span>}
                            {p.code}
                          </td>
                          <td className="px-4 py-2">{p.name}</td>
                          <td className="px-4 py-2 text-right font-mono">
                            <div>{p.price.toFixed(2)}</div>
                            {isHighRisk ? (
                              <div className="text-[10px] text-amber-600 font-mono">上限 {Number(p.safe_price_max || 0).toFixed(2)}</div>
                            ) : null}
                          </td>
                          <td className="px-4 py-2 text-center">
                            <span className={`inline-block px-2 py-0.5 rounded border text-xs font-bold ${scoreBg(p.score)}`}>
                              {p.score}
                            </span>
                          </td>
                          <td className="px-4 py-2">
                            {(p.buy_points || []).length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {(p.buy_points || []).map((b, i) => {
                                  const high = b.includes("高位");
                                  const cls = high
                                    ? "px-1.5 py-0.5 text-xs bg-amber-500/15 text-amber-700 rounded border border-amber-500/40"
                                    : "px-1.5 py-0.5 text-xs bg-green-500/15 text-green-700 rounded border border-green-500/30";
                                  return <span key={i} className={cls}>{b}</span>;
                                })}
                              </div>
                            ) : (
                              <span className="text-muted-foreground text-xs">-</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-center">
                            <span className={
                              p.last_bi_dir === "up" ? "text-green-600 font-medium" :
                              p.last_bi_dir === "down" ? "text-red-600 font-medium" :
                              "text-muted-foreground"
                            }>
                              {p.last_bi_dir === "up" ? "↑向上" : p.last_bi_dir === "down" ? "↓向下" : "-"}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-center text-xs text-muted-foreground">
                            {p.bi_count}笔 / {p.zs_count}中枢
                          </td>
                          <td className="px-4 py-2 text-center text-xs">
                            {p.in_zs ? (
                              <span className="text-indigo-600">
                                中枢内 {p.zs_range ? `[${p.zs_range[0].toFixed(2)}~${p.zs_range[1].toFixed(2)}]` : ""}
                              </span>
                            ) : p.zs_range && p.price > p.zs_range[1] ? (
                              <span className={isHighRisk ? "text-amber-600" : "text-green-600"}>
                                {isHighRisk ? "⚠ 中枢上方（高位）" : "中枢上方（三买区）"}
                              </span>
                            ) : p.zs_range && p.price < p.zs_range[0] ? (
                              <span className="text-red-600">中枢下方（弱势）</span>
                            ) : (
                              <span className="text-muted-foreground">无明确中枢</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-center">
                            <button
                              onClick={(e) => { e.stopPropagation(); handlePickClick(p); }}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs border rounded hover:bg-primary hover:text-primary-foreground transition-colors"
                            >
                              <Search className="h-3 w-3" />
                              缠论图
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab: 结构图 */}
      {tab === "chart" && result && (
        <div className="space-y-4">
          {/* 个股头部信息 + 评分 */}
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h2 className="text-xl font-semibold">
                {result.code}
              </h2>
              {result.analysis && (
                <div className="text-sm text-muted-foreground mt-1 flex flex-wrap gap-4">
                  <span>日期: {result.analysis.date}</span>
                  <span>收盘价: <strong className="text-foreground">{result.analysis.price.toFixed(2)}</strong></span>
                  <span>笔: {result.analysis.bi_count}</span>
                  <span>中枢: {result.analysis.zs_count}</span>
                  <span>方向: {
                    result.analysis.last_bi_dir === "up" ? <span className="text-green-600">向上笔</span> :
                    result.analysis.last_bi_dir === "down" ? <span className="text-red-600">向下笔</span> :
                    "不明"
                  }</span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-4">
              {typeof result.score === "number" && (
                <div className="flex flex-col items-center px-4 py-2 rounded-lg border bg-card">
                  <span className="text-xs text-muted-foreground mb-1 inline-flex items-center gap-1">
                    <Target className="h-3 w-3" />缠论综合评分
                  </span>
                  <span className={`text-3xl font-bold ${scoreColor(result.score)}`}>
                    {result.score}
                    <span className="text-sm font-medium text-muted-foreground">/100</span>
                  </span>
                </div>
              )}
              {result.buy_point_info?.buy_points && result.buy_point_info.buy_points.length > 0 && (
                <div className="flex flex-col items-start">
                  <span className="text-xs text-muted-foreground mb-1">买点信号</span>
                  <div className="flex gap-1 flex-wrap">
                    {result.buy_point_info.buy_points.map((b, i) => (
                      <span key={i} className="px-2 py-1 text-xs bg-green-500/15 text-green-700 rounded border border-green-500/30 font-medium">
                        {b}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 图例 */}
          <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="inline-block w-5 h-0.5 bg-green-600" />向上笔
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-5 h-0.5 bg-red-600" />向下笔
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-5 h-3 bg-indigo-500/20 border border-indigo-500 border-dashed" />中枢（含上/下沿）
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-0 h-0 border-l-4 border-r-4 border-b-6 border-l-transparent border-r-transparent border-b-green-600" />买点
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-0 h-0 border-l-4 border-r-4 border-t-6 border-l-transparent border-r-transparent border-t-red-600" />卖点
            </span>
          </div>

          {/* 图表 */}
          <div className="border rounded-lg p-4 bg-card">
            <CzscChart
              klines={result.klines || []}
              bis={result.bis || []}
              zsList={result.zs_list || []}
              buyPoints={chartBuyPoints}
              height={440}
            />
          </div>

          {/* 分析建议 */}
          {result.analysis && (
            <div className="p-4 bg-muted/30 rounded-lg text-sm space-y-2">
              <div className="font-medium inline-flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-primary" />解读建议
              </div>
              {result.analysis.points.map((p, i) => (
                <div key={i} className="flex items-start gap-1.5 pl-4">
                  <span className="w-1 h-1 rounded-full bg-primary mt-1.5 shrink-0" />
                  <span>{p}</span>
                </div>
              ))}
              <div className={`pl-4 font-medium ${scoreColor(result.score || 0)}`}>
                {result.analysis.suggestion}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab: 笔列表 */}
      {tab === "bis" && result && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">#</th>
                <th className="px-4 py-2 text-left font-medium">起始日期</th>
                <th className="px-4 py-2 text-left font-medium">结束日期</th>
                <th className="px-4 py-2 text-center font-medium">方向</th>
                <th className="px-4 py-2 text-right font-medium">高点</th>
                <th className="px-4 py-2 text-right font-medium">低点</th>
                <th className="px-4 py-2 text-right font-medium">能量</th>
              </tr>
            </thead>
            <tbody>
              {(result.bis || []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂未识别出笔</td>
                </tr>
              )}
              {(result.bis || []).map((b, i) => (
                <tr key={i} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-2 text-xs text-muted-foreground">{i + 1}</td>
                  <td className="px-4 py-2 font-mono text-xs">{b.sdt}</td>
                  <td className="px-4 py-2 font-mono text-xs">{b.edt}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={
                      b.direction === "up" ? "text-green-600 font-medium" :
                      b.direction === "down" ? "text-red-600 font-medium" :
                      "text-muted-foreground"
                    }>
                      {b.direction === "up" ? "↑ 向上" : b.direction === "down" ? "↓ 向下" : "-"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-red-600">{b.high.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right font-mono text-green-600">{b.low.toFixed(2)}</td>
                  <td className="px-4 py-2 text-right font-mono text-muted-foreground">
                    {typeof b.power === "number" ? b.power.toFixed(2) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab: 中枢列表 */}
      {tab === "zs" && result && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">#</th>
                <th className="px-4 py-2 text-left font-medium">起始</th>
                <th className="px-4 py-2 text-left font-medium">结束</th>
                <th className="px-4 py-2 text-right font-medium">下沿 zdd</th>
                <th className="px-4 py-2 text-right font-medium">上沿 zgg</th>
                <th className="px-4 py-2 text-right font-medium">中枢幅度</th>
              </tr>
            </thead>
            <tbody>
              {(result.zs_list || []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">暂未形成中枢</td>
                </tr>
              )}
              {(result.zs_list || []).map((z, i) => {
                const pct = z.zgg && z.zdd ? ((z.zgg - z.zdd) / z.zdd * 100) : 0;
                return (
                  <tr key={i} className="border-t hover:bg-muted/30">
                    <td className="px-4 py-2 text-xs text-muted-foreground">{i + 1}</td>
                    <td className="px-4 py-2 font-mono text-xs">{z.sdt}</td>
                    <td className="px-4 py-2 font-mono text-xs">{z.edt}</td>
                    <td className="px-4 py-2 text-right font-mono text-green-700">{z.zdd.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right font-mono text-red-700">{z.zgg.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right font-mono">{pct.toFixed(2)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab: 信号列表 */}
      {tab === "signals" && result && (
        <div className="border rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-muted/50 text-xs text-muted-foreground border-b">
            基于 DEFAULT_SIGNALS（CXT 缠论核心 + TAS 技术指标）当前最后一根K线的信号
          </div>
          <table className="w-full text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">k1 (维度)</th>
                <th className="px-4 py-2 text-left font-medium">k2</th>
                <th className="px-4 py-2 text-left font-medium">k3</th>
                <th className="px-4 py-2 text-left font-medium">k4</th>
                <th className="px-4 py-2 text-left font-medium">k5</th>
                <th className="px-4 py-2 text-right font-medium">score</th>
              </tr>
            </thead>
            <tbody>
              {(result.signals || []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    暂无触发信号
                  </td>
                </tr>
              )}
              {(result.signals || []).map((s, i) => (
                <tr key={i} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-2 font-mono text-xs text-indigo-700">{s.k1 || "-"}</td>
                  <td className="px-4 py-2 text-xs">{s.k2 || "-"}</td>
                  <td className="px-4 py-2 text-xs">{s.k3 || "-"}</td>
                  <td className="px-4 py-2 text-xs">{s.k4 || "-"}</td>
                  <td className="px-4 py-2 text-xs">{s.k5 || "-"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">
                    {s.score || "-"}
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

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { RefreshCw, Zap, TrendingUp, TrendingDown, BarChart3, Calendar, Eye, Plus, Trash2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

interface AuctionStat {
  count: number; total_vol: number; total_amount: number; avg_ratio?: number;
}

interface AuctionStock {
  code: string; name: string; auction_vol: number; auction_amount: number;
  auction_price: number; open_price: number;
}

interface DateInfo {
  date: string; count: number; total_vol: number;
}

interface CompareStock {
  code: string; name: string; vol_today: number; vol_prev: number;
  vol_chg: number; vol_pct: number; price_today: number;
  auction_chg_today: number | null;
}

interface ExpectStock {
  code: string; name: string; prev_close: number; status: string; E?: number; stop?: number;
}

interface ExpectAuctionItem {
  code: string; name: string; auction_price: number; auction_change_pct: number;
  today_vol: number; prev_vol: number; vol_ratio: number; expectation: string; suggestion: string;
}

interface ConceptStockBrief {
  code: string; name: string; mcap_yi?: number; vol: number; chg_pct: number; limit_n?: number;
  yest_vol?: number | null; vol_ratio?: number | null;
}

interface ConceptItem {
  tag: string; n: number; red_ratio: number; hh_n: number; avg_chg: number;
  score: number; max_limit: number; total_amount: number; signal: string;
  limit_up_open_n?: number;
  anchor: ConceptStockBrief | null; zhongjun: ConceptStockBrief | null;
  tanxing: ConceptStockBrief[]; top_limit: ConceptStockBrief[];
}

function volClass(v: number) {
  if (v > 0) return "text-red-600";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function formatVol(v: number) {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
  return String(v);
}

function auctionChgCell(v: number | null) {
  if (v == null) return <td className="px-3 py-2 text-right text-muted-foreground">-</td>;
  const cls = v >= 0 ? "text-red-600" : "text-green-600";
  return <td className={`px-3 py-2 text-right font-medium ${cls}`}>{v >= 0 ? "+" : ""}{v.toFixed(2)}%</td>;
}

export function AuctionBoard() {
  const [dates, setDates] = useState<DateInfo[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [stocks, setStocks] = useState<AuctionStock[]>([]);
  const [stats, setStats] = useState<AuctionStat | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [tab, setTab] = useState<"volume" | "compare" | "expectation" | "concept">("volume");
  const [compareData, setCompareData] = useState<{ date1: string; date2: string; gainers: CompareStock[]; losers: CompareStock[]; increase: number; decrease: number; total: number } | null>(null);
  const [expectStocks, setExpectStocks] = useState<ExpectStock[]>([]);
  const [expectItems, setExpectItems] = useState<ExpectAuctionItem[]>([]);
  const [expectLoading, setExpectLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [conceptData, setConceptData] = useState<ConceptItem[]>([]);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [expandedConcept, setExpandedConcept] = useState<string | null>(null);
  const [analysisSource, setAnalysisSource] = useState<"industry" | "concept">("industry");

  const fetchDates = async (selectLatest = false) => {
    try {
      const data = await api.tools.get<any>("/auction/dates");
      setDates(data.dates || []);
      if (data.dates?.length > 0 && (selectLatest || !selectedDate)) {
        setSelectedDate(data.dates[0].date);
      }
    } catch (e) { /* ignore */ }
  };

  const fetchDateData = async (date: string) => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>(`/auction/latest?date=${encodeURIComponent(date)}&limit=100`);
      setStocks(data.stocks || []);
      setStats(data.stats || null);
    } catch (e) { /* ignore */ }
    finally { setLoading(false); }
  };

  const fetchCompare = async () => {
    if (dates.length < 2) return;
    const d1 = selectedDate || dates[0].date;
    const d2 = dates.find(d => d.date !== d1)?.date || dates[1]?.date;
    if (!d2) return;
    setLoading(true);
    try {
      const data = await api.tools.get<any>(`/auction/compare?date1=${encodeURIComponent(d1)}&date2=${encodeURIComponent(d2)}&top=30`);
      setCompareData(data);
    } catch (e) { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleCollect = async () => {
    setCollecting(true);
    try {
      const data = await api.tools.post<any>("/auction/collect");
        if (data.status === "exists") {
          toast.info("已使用今日已有竞价数据");
        } else if (data.status === "no_data") {
          toast.error(data.error || "今日尚无竞价数据（09:30后无法采集）");
        } else if (data.status === "collected") {
          toast.success(`已采集 ${data.count} 只股票竞价数据`);
        }
        await fetchDates(true);
        fetchCompare();
        fetchExpectData();
        fetchConceptAnalysis();
    } catch (e) { /* ignore */ }
    finally { setCollecting(false); }
  };

  const fetchExpectData = async () => {
    setExpectLoading(true);
    try {
      const data = await api.tools.get<any>("/expectations");
      const pos = data.positions || [];
      setExpectStocks(pos);
      if (pos.length > 0) {
        const codes = pos.map((s: ExpectStock) => s.code).join(",");
        const aData = await api.tools.get<any>(`/watchlist-auction?codes=${codes}`);
        const merged: Record<string, any> = { ...(aData.auction || {}) };
        const saved = data.auction_data || {};
        for (const [code, v] of Object.entries(saved)) {
          if (!merged[code]) merged[code] = {};
          merged[code].today_vol = (v as any).today_vol ?? merged[code].today_vol;
          merged[code].prev_vol = (v as any).prev_vol ?? merged[code].prev_vol;
          merged[code].auction_price = (v as any).auction_price ?? merged[code].auction_price;
        }
        const items: ExpectAuctionItem[] = pos.map((s: ExpectStock) => {
          const a = merged[s.code] || {};
          const todayVol = Math.round(a.today_vol || 0);
          const prevVol = Math.round(a.prev_vol || 0);
          const volRatio = prevVol > 0 ? todayVol / prevVol : 0;
          const auctionChg = s.prev_close > 0 && (a.auction_price ?? 0) > 0
            ? ((a.auction_price - s.prev_close) / s.prev_close * 100)
            : 0;
          const exp = calcExpectation(auctionChg, volRatio);
          return {
            code: s.code, name: s.name,
            auction_price: a.auction_price || 0,
            auction_change_pct: auctionChg,
            today_vol: todayVol, prev_vol: prevVol,
            vol_ratio: volRatio,
            expectation: exp.type, suggestion: calcSuggestion(exp.type),
          };
        });
        setExpectItems(items);
      } else {
        setExpectItems([]);
      }
    } catch { /* ignore */ }
    finally { setExpectLoading(false); }
  };

  const fetchConceptAnalysis = async (d?: string, src?: "industry" | "concept") => {
    setConceptLoading(true);
    try {
      const date = d || selectedDate || dates[0]?.date;
      if (!date) { toast.warning("请先选择日期"); return; }
      const s = src || analysisSource;
      const data = await api.tools.get<any>(`/auction/concept-analysis?date=${encodeURIComponent(date)}&source=${s}`);
      if (data.error) { toast.error(`分析失败: ${data.error}`); return; }
      setConceptData(data.concepts || []);
      if (!data.concepts?.length) toast.info("该日期无数据");
    } catch (e: any) { toast.error(`请求失败: ${e.message || e}`); }
    finally { setConceptLoading(false); }
  };

  const handleAddStock = async () => {
    if (!newCode.trim()) return;
    try {
      await api.tools.post<any>("/expectations/add", { code: newCode.trim() });
      setNewCode("");
      setShowAddModal(false);
      fetchExpectData();
    } catch { /* ignore */ }
  };

  const handleRemoveStock = async (code: string) => {
    try {
      await api.tools.post<any>("/expectations/remove", { code });
      fetchExpectData();
    } catch { /* ignore */ }
  };

  const calcExpectation = (changePct: number, volRatio: number) => {
    if (changePct > 3 && volRatio >= 1.5) return { type: "超预期", color: "text-red-600" };
    if (changePct >= -1 && changePct <= 1 && volRatio >= 0.8 && volRatio <= 1.2) return { type: "符合预期", color: "text-green-600" };
    if (changePct < -1 || volRatio < 0.7) return { type: "不及预期", color: "text-yellow-600" };
    return { type: "正常", color: "text-muted-foreground" };
  };

  const calcSuggestion = (expectation: string) => {
    switch (expectation) {
      case "超预期": return "加仓/持有";
      case "符合预期": return "观察3-5分钟";
      case "不及预期": return "反抽减亏";
      default: return "观望";
    }
  };

  useEffect(() => { fetchDates(); }, []);

  useEffect(() => {
    if (selectedDate) {
      if (tab === "compare") fetchCompare();
      else if (tab === "expectation") fetchExpectData();
      else if (tab === "concept") fetchConceptAnalysis(selectedDate);
      else fetchDateData(selectedDate);
    }
  }, [selectedDate, tab, analysisSource]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">集合竞价看板</h1>
          <p className="text-sm text-muted-foreground mt-1">每日竞价量能监控与对比分析</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCollect}
            disabled={collecting}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-purple-600 text-white rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
          >
            <Zap className={`h-4 w-4 ${collecting ? "animate-spin" : ""}`} />
            {collecting ? "采集中..." : "采集竞价"}
          </button>
          <button
            onClick={() => { if (selectedDate) fetchDateData(selectedDate); }}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
      </div>

      {/* Date Selector + Stats */}
      <div className="flex flex-wrap items-center gap-3">
        <Calendar className="h-4 w-4 text-muted-foreground" />
        <select
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="border rounded-md px-3 py-1.5 text-sm bg-background"
        >
          {dates.map((d) => (
            <option key={d.date} value={d.date}>
              {d.date}（{d.count}只）
            </option>
          ))}
        </select>
        <span className="text-xs text-muted-foreground">
          共 {dates.length} 个交易日
        </span>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">股票数量</div>
            <p className="text-xl font-bold">{stats.count}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">竞价总量</div>
            <p className="text-xl font-bold">{formatVol(stats.total_vol)}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">竞价总额</div>
            <p className="text-xl font-bold">{formatVol(stats.total_amount)}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">平均竞价比</div>
            <p className="text-xl font-bold">{stats.avg_ratio}%</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b">
        {[
          { key: "volume" as const, label: "竞价量排行", icon: BarChart3 },
          { key: "compare" as const, label: "竞价对比", icon: TrendingDown },
          { key: "expectation" as const, label: "预期管理", icon: Eye },
          { key: "concept" as const, label: "竞价分析", icon: Sparkles },
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

      {tab === "compare" && compareData ? (
        <div className="space-y-6">
          <div className="grid gap-4 grid-cols-4">
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">对比日期</div>
              <p className="text-sm font-medium">{compareData.date2} → {compareData.date1}</p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">共同股票</div>
              <p className="text-xl font-bold">{compareData.total}</p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                <TrendingUp className="h-4 w-4 text-red-500" /> 放量
              </div>
              <p className="text-xl font-bold text-red-600">{compareData.increase}</p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                <TrendingDown className="h-4 w-4 text-green-500" /> 缩量
              </div>
              <p className="text-xl font-bold text-green-600">{compareData.decrease}</p>
            </div>
          </div>

          {/* Gainers */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-red-500" />
              <h2 className="font-semibold">放量排行（竞价量增幅最大）</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">排名</th>
                    <th className="px-3 py-2 text-left font-medium">代码</th>
                    <th className="px-3 py-2 text-left font-medium">名称</th>
                    <th className="px-3 py-2 text-right font-medium">今日竞价量（手）</th>
                    <th className="px-3 py-2 text-right font-medium">昨日竞价量（手）</th>
                    <th className="px-3 py-2 text-right font-medium">变化量</th>
                    <th className="px-3 py-2 text-right font-medium">变化%</th>
                    <th className="px-3 py-2 text-right font-medium">竞价价</th>
                    <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                  </tr>
                </thead>
                <tbody>
                  {compareData.gainers.map((s, i) => (
                    <tr key={s.code} className="border-t hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{s.code}</td>
                      <td className="px-3 py-2">{s.name}</td>
                      <td className="px-3 py-2 text-right">{Math.round(s.vol_today / 100).toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{Math.round(s.vol_prev / 100).toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${volClass(s.vol_chg)}`}>
                        {(s.vol_chg > 0 ? "+" : "") + Math.round(Math.abs(s.vol_chg) / 100).toLocaleString()}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${volClass(s.vol_pct)}`}>
                        {s.vol_pct >= 999 ? "NEW" : `${s.vol_pct >= 0 ? "+" : ""}${s.vol_pct.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-2 text-right">{s.price_today?.toFixed(2)}</td>
                      {auctionChgCell(s.auction_chg_today)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Losers */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-green-500" />
              <h2 className="font-semibold">缩量排行（竞价量降幅最大）</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">排名</th>
                    <th className="px-3 py-2 text-left font-medium">代码</th>
                    <th className="px-3 py-2 text-left font-medium">名称</th>
                    <th className="px-3 py-2 text-right font-medium">今日竞价量（手）</th>
                    <th className="px-3 py-2 text-right font-medium">昨日竞价量（手）</th>
                    <th className="px-3 py-2 text-right font-medium">变化量</th>
                    <th className="px-3 py-2 text-right font-medium">变化%</th>
                    <th className="px-3 py-2 text-right font-medium">竞价价</th>
                    <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                  </tr>
                </thead>
                <tbody>
                  {compareData.losers.map((s, i) => (
                    <tr key={s.code} className="border-t hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{s.code}</td>
                      <td className="px-3 py-2">{s.name}</td>
                      <td className="px-3 py-2 text-right">{Math.round(s.vol_today / 100).toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{Math.round(s.vol_prev / 100).toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${volClass(s.vol_chg)}`}>
                        {(s.vol_chg > 0 ? "+" : "") + Math.round(Math.abs(s.vol_chg) / 100).toLocaleString()}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${volClass(s.vol_pct)}`}>
                        {s.vol_pct >= 999 ? "NEW" : `${s.vol_pct >= 0 ? "+" : ""}${s.vol_pct.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-2 text-right">{s.price_today?.toFixed(2)}</td>
                      {auctionChgCell(s.auction_chg_today)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : tab === "expectation" ? (
        <div className="space-y-4">
          {/* 预期管理工具条 */}
          <div className="flex items-center gap-2 justify-end">
            <button
              onClick={() => setShowAddModal(true)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors"
            >
              <Plus className="h-4 w-4" />
              添加自选股
            </button>
            <button
              onClick={fetchExpectData}
              disabled={expectLoading}
              className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${expectLoading ? "animate-spin" : ""}`} />
              刷新
            </button>
          </div>

          {/* 预期管理表格 */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <div className="px-4 py-3 border-b bg-muted/30">
              <h2 className="font-semibold">自选股竞价监控</h2>
            </div>
            {expectLoading ? (
              <div className="p-8 text-center text-muted-foreground">加载中...</div>
            ) : expectStocks.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">
                暂无自选股，点击"添加自选股"开始
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">代码</th>
                      <th className="px-3 py-2 text-left font-medium">名称</th>
                      <th className="px-3 py-2 text-right font-medium">竞价价</th>
                      <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                      <th className="px-3 py-2 text-right font-medium">今竞价量（手）</th>
                      <th className="px-3 py-2 text-right font-medium">昨竞价量（手）</th>
                      <th className="px-3 py-2 text-right font-medium">量比</th>
                      <th className="px-3 py-2 text-center font-medium">预期</th>
                      <th className="px-3 py-2 text-center font-medium">建议</th>
                      <th className="px-3 py-2 text-center font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {expectItems.map((item) => {
                      const exp = calcExpectation(item.auction_change_pct, item.vol_ratio);
                      const suggestion = calcSuggestion(exp.type);
                      return (
                        <tr key={item.code} className="border-t hover:bg-muted/30">
                          <td className="px-3 py-2 font-mono">{item.code}</td>
                          <td className="px-3 py-2">{item.name}</td>
                          <td className="px-3 py-2 text-right">{item.auction_price > 0 ? item.auction_price.toFixed(2) : "-"}</td>
                          <td className={`px-3 py-2 text-right font-medium ${item.auction_change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                            {item.auction_price > 0 ? `${item.auction_change_pct >= 0 ? "+" : ""}${item.auction_change_pct.toFixed(2)}%` : "-"}
                          </td>
                          <td className="px-3 py-2 text-right font-medium">{item.today_vol ? item.today_vol.toLocaleString() : "-"}</td>
                          <td className="px-3 py-2 text-right text-muted-foreground">{item.prev_vol ? item.prev_vol.toLocaleString() : "-"}</td>
                          <td className={`px-3 py-2 text-right font-medium ${item.vol_ratio > 1 ? "text-red-600" : item.vol_ratio > 0 && item.vol_ratio < 1 ? "text-green-600" : ""}`}>
                            {item.vol_ratio > 0 ? item.vol_ratio.toFixed(2) : "-"}
                          </td>
                          <td className={`px-3 py-2 text-center font-medium ${exp.color}`}>{exp.type}</td>
                          <td className="px-3 py-2 text-center">{suggestion}</td>
                          <td className="px-3 py-2 text-center">
                            <button
                              onClick={() => handleRemoveStock(item.code)}
                              className="p-1 text-muted-foreground hover:text-red-600 rounded"
                              title="删除"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 添加自选股弹窗 */}
          {showAddModal && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
              <div className="bg-card rounded-lg p-6 w-96 shadow-lg">
                <h3 className="text-lg font-semibold mb-4">添加自选股</h3>
                <input
                  autoFocus
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAddStock(); if (e.key === "Escape") setShowAddModal(false); }}
                  placeholder="输入股票代码，如 sh600519"
                  className="w-full border rounded-md px-3 py-2 text-sm mb-4"
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setShowAddModal(false)}
                    className="px-4 py-2 text-sm border rounded-md hover:bg-muted"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleAddStock}
                    className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90"
                  >
                    添加
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : tab === "concept" ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2 justify-between">
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setAnalysisSource("industry"); }}
                className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                  analysisSource === "industry"
                    ? "bg-primary text-primary-foreground"
                    : "border text-muted-foreground hover:text-foreground"
                }`}
              >
                行业板块
              </button>
              <button
                onClick={() => { setAnalysisSource("concept"); }}
                className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                  analysisSource === "concept"
                    ? "bg-primary text-primary-foreground"
                    : "border text-muted-foreground hover:text-foreground"
                }`}
              >
                概念板块
              </button>
            </div>
            <button
              onClick={() => fetchConceptAnalysis(selectedDate, analysisSource)}
              disabled={conceptLoading}
              className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${conceptLoading ? "animate-spin" : ""}`} />
              刷新
            </button>
          </div>

          {/* Summary Section */}
          {conceptData.length > 0 && (
            <div className="border rounded-lg bg-card p-4 space-y-3">
              {(() => {
                const top = conceptData[0];
                const volBadge = (s: ConceptStockBrief) => {
                  const vr = s.vol_ratio;
                  if (vr == null) return null;
                  return vr >= 1.2
                    ? <span className="text-red-600 font-medium">量比{vr.toFixed(2)}</span>
                    : vr >= 0.8
                      ? <span className="text-muted-foreground">量比{vr.toFixed(2)}</span>
                      : <span className="text-green-600 font-medium">量比{vr.toFixed(2)}</span>;
                };
                const cmpCol = (s: ConceptStockBrief) => s.chg_pct >= 0 ? "text-red-600" : "text-green-600";
                return (
                  <>
                    <div>
                      <span className="font-bold text-base">【最强板块】{top.tag}</span>
                      <span className="ml-2 text-sm text-muted-foreground">评分 {top.score.toFixed(0)} · 红盘率 {(top.red_ratio * 100).toFixed(0)}% · 均涨幅 {top.avg_chg >= 0 ? "+" : ""}{top.avg_chg.toFixed(2)}%</span>
                    </div>
                    <div className="grid grid-cols-3 gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">锚点 </span>
                        <span className="font-medium">{top.anchor?.name}({top.anchor?.code})</span>
                        {top.anchor && (
                          <>
                            <span className={`ml-2 ${cmpCol(top.anchor)}`}>{top.anchor.chg_pct >= 0 ? "+" : ""}{top.anchor.chg_pct.toFixed(2)}%</span>
                            <span className="ml-2 text-xs text-muted-foreground">昨{top.anchor.yest_vol ?? "?"}→{top.anchor.vol} </span>
                            {volBadge(top.anchor)}
                          </>
                        )}
                      </div>
                      <div>
                        <span className="text-muted-foreground">中军 </span>
                        <span className="font-medium">{top.zhongjun?.name}({top.zhongjun?.code})</span>
                        {top.zhongjun && (
                          <>
                            <span className={`ml-2 ${cmpCol(top.zhongjun)}`}>{top.zhongjun.chg_pct >= 0 ? "+" : ""}{top.zhongjun.chg_pct.toFixed(2)}%</span>
                            <span className="ml-2 text-xs text-muted-foreground">昨{top.zhongjun.yest_vol ?? "?"}→{top.zhongjun.vol} </span>
                            {volBadge(top.zhongjun)}
                          </>
                        )}
                      </div>
                      <div>
                        <span className="text-muted-foreground">弹性 </span>
                        {top.tanxing.slice(0, 2).map(t => (
                          <span key={t.code} className="mr-3">
                            <span className="font-medium">{t.name}</span>
                            <span className={`ml-1 ${cmpCol(t)}`}>{t.chg_pct >= 0 ? "+" : ""}{t.chg_pct.toFixed(2)}%</span>
                            <span className="ml-1 text-xs text-muted-foreground">量比{t.vol_ratio?.toFixed(2) ?? "N/A"}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                    {top.max_limit > 0 && (
                      <div className="text-xs text-muted-foreground">
                        最高板: {top.top_limit.map(ls => `${ls.name}(${ls.limit_n}板)`).join(" | ")}
                      </div>
                    )}

                    {/* 次强板块 */}
                    {conceptData.length > 1 && (
                      <div className="pt-2 border-t text-sm">
                        <span className="font-semibold">【次强板块】</span>
                        <span className="font-medium">{conceptData[1].tag}</span>
                        <span className="ml-2 text-muted-foreground">评分 {conceptData[1].score.toFixed(0)} · 红盘率 {(conceptData[1].red_ratio * 100).toFixed(0)}% · 均涨幅 {conceptData[1].avg_chg >= 0 ? "+" : ""}{conceptData[1].avg_chg.toFixed(2)}%</span>
                      </div>
                    )}

                    {/* 关注推荐 */}
                    {(() => {
                      const recs: { tag: string; role: string; s: ConceptStockBrief }[] = [];
                      conceptData.slice(0, 5).forEach(c => {
                        const check = (s: ConceptStockBrief | null, role: string) => {
                          if (s && s.vol_ratio != null && s.vol_ratio >= 1.2 && s.chg_pct > 0)
                            recs.push({ tag: c.tag, role, s });
                        };
                        check(c.anchor, "锚点");
                        check(c.zhongjun, "中军");
                        (c.tanxing || []).forEach(t => check(t, "弹性"));
                      });
                      if (recs.length === 0) return null;
                      return (
                        <div className="pt-2 border-t text-sm">
                          <span className="font-semibold">【关注推荐】</span>
                          {recs.slice(0, 6).map((r, i) => (
                            <span key={i} className="mr-3">
                              <span className="text-muted-foreground">{r.tag}</span>
                              <span className="ml-1">{r.role} </span>
                              <span className="font-medium">{r.s.name}</span>
                              <span className={`ml-1 ${cmpCol(r.s)}`}>{r.s.chg_pct >= 0 ? "+" : ""}{r.s.chg_pct.toFixed(2)}%</span>
                              <span className="ml-1 text-xs text-muted-foreground">量比{r.s.vol_ratio?.toFixed(2)}</span>
                            </span>
                          ))}
                        </div>
                      );
                    })()}
                  </>
                );
              })()}
            </div>
          )}

          <div className="border rounded-lg bg-card overflow-hidden">
            <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-purple-500" />
              <h2 className="font-semibold">{analysisSource === "industry" ? "行业板块竞价分析" : "概念板块竞价分析"}</h2>
              <span className="text-xs text-muted-foreground ml-auto">
                红盘率×30 + 高开占比×20 + 均涨幅×15 + 个股数×10 + 连板加分×15 + 竞价涨停开×10
              </span>
            </div>
            {conceptLoading ? (
              <div className="p-8 text-center text-muted-foreground">加载中...</div>
            ) : conceptData.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">暂无数据，请先采集竞价</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">排名</th>
                      <th className="px-3 py-2 text-left font-medium">{analysisSource === "industry" ? "行业" : "概念"}</th>
                      <th className="px-3 py-2 text-right font-medium">个股</th>
                      <th className="px-3 py-2 text-right font-medium">红盘率</th>
                      <th className="px-3 py-2 text-right font-medium">高开&gt;2%</th>
                      <th className="px-3 py-2 text-right font-medium">均涨幅</th>
                      <th className="px-3 py-2 text-right font-medium">最高板</th>
                      <th className="px-3 py-2 text-right font-medium">评分</th>
                      <th className="px-3 py-2 text-left font-medium">锚点</th>
                      <th className="px-3 py-2 text-left font-medium">中军</th>
                      <th className="px-3 py-2 text-center font-medium">信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conceptData.map((c, i) => {
                      const isExpanded = expandedConcept === c.tag;
                      return (
                        <>
                          <tr
                            key={c.tag}
                            className="border-t hover:bg-muted/30 cursor-pointer transition-colors"
                            onClick={() => setExpandedConcept(isExpanded ? null : c.tag)}
                          >
                            <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                            <td className="px-3 py-2 font-medium">{c.tag}</td>
                            <td className="px-3 py-2 text-right">{c.n}</td>
                            <td className="px-3 py-2 text-right">{(c.red_ratio * 100).toFixed(0)}%</td>
                            <td className="px-3 py-2 text-right font-medium text-red-600">{c.hh_n}</td>
                            <td className={`px-3 py-2 text-right font-medium ${c.avg_chg >= 0 ? "text-red-600" : "text-green-600"}`}>
                              {c.avg_chg >= 0 ? "+" : ""}{c.avg_chg.toFixed(2)}%
                            </td>
                            <td className="px-3 py-2 text-right font-medium">
                              {c.max_limit > 0 ? (
                                <span className="text-amber-600 font-bold">{c.max_limit}板</span>
                              ) : "—"}
                            </td>
                            <td className="px-3 py-2 text-right font-bold">{c.score.toFixed(0)}</td>
                            <td className="px-3 py-2">
                              <span className="text-xs">{c.anchor?.name || "—"}</span>
                            </td>
                            <td className="px-3 py-2">
                              <span className="text-xs">{c.zhongjun?.name || "—"}</span>
                            </td>
                            <td className="px-3 py-2 text-center">
                              {c.signal ? (
                                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                  c.signal.includes("超预期") ? "bg-red-100 text-red-700" :
                                  c.signal.includes("不及预期") ? "bg-yellow-100 text-yellow-700" :
                                  c.signal.includes("强势") ? "bg-blue-100 text-blue-700" :
                                  c.signal.includes("弱") ? "bg-gray-100 text-gray-500" : ""
                                }`}>
                                  {c.signal}
                                </span>
                              ) : "—"}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${c.tag}-detail`} className="bg-muted/20">
                              <td colSpan={11} className="px-6 py-3">
                                <div className="grid grid-cols-4 gap-4 text-xs">
                                  <div>
                                    <div className="text-muted-foreground mb-1">锚点</div>
                                    <div className="font-medium">{c.anchor?.name}</div>
                                    {c.anchor?.mcap_yi && <div className="text-muted-foreground">市值{c.anchor.mcap_yi.toFixed(0)}亿</div>}
                                    <div className={c.anchor && (c.anchor.chg_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"}>
                                      开盘 {c.anchor ? `${c.anchor.chg_pct >= 0 ? "+" : ""}${c.anchor.chg_pct.toFixed(2)}%` : "—"}
                                    </div>
                                    <div className="text-muted-foreground">
                                      竞价量 {c.anchor?.vol?.toLocaleString() ?? "—"}
                                      {c.anchor?.yest_vol != null && (
                                        <span className="ml-1">(昨{c.anchor.yest_vol.toLocaleString()} {c.anchor.vol_ratio != null ? <span className={c.anchor.vol_ratio >= 1.2 ? "text-red-500" : c.anchor.vol_ratio < 0.8 ? "text-green-500" : ""}>量比{c.anchor.vol_ratio.toFixed(2)}</span> : ""})</span>
                                      )}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-muted-foreground mb-1">中军</div>
                                    <div className="font-medium">{c.zhongjun?.name}</div>
                                    <div className={c.zhongjun && (c.zhongjun.chg_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"}>
                                      开盘 {c.zhongjun ? `${c.zhongjun.chg_pct >= 0 ? "+" : ""}${c.zhongjun.chg_pct.toFixed(2)}%` : "—"}
                                    </div>
                                    <div className="text-muted-foreground">
                                      竞价量 {c.zhongjun?.vol.toLocaleString()}
                                      {c.zhongjun?.yest_vol != null && (
                                        <span className="ml-1">(昨{c.zhongjun.yest_vol.toLocaleString()} {c.zhongjun.vol_ratio != null ? <span className={c.zhongjun.vol_ratio >= 1.2 ? "text-red-500" : c.zhongjun.vol_ratio < 0.8 ? "text-green-500" : ""}>量比{c.zhongjun.vol_ratio.toFixed(2)}</span> : ""})</span>
                                      )}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-muted-foreground mb-1">最高板</div>
                                    {c.top_limit.length > 0 ? (
                                      c.top_limit.map(t => (
                                        <div key={t.name} className="font-medium text-amber-600">
                                          {t.name} {t.limit_n}板
                                        </div>
                                      ))
                                    ) : (
                                      <div className="text-muted-foreground">—</div>
                                    )}
                                  </div>
                                  <div>
                                    <div className="text-muted-foreground mb-1">弹性</div>
                                    {c.tanxing.length > 0 ? (
                                      c.tanxing.map(t => (
                                        <div key={t.name}>
                                          <span className="text-red-600">{t.name} {t.chg_pct >= 0 ? "+" : ""}{t.chg_pct.toFixed(2)}%</span>
                                          {t.yest_vol != null && (
                                            <span className="ml-1 text-muted-foreground">
                                              量比{t.vol_ratio?.toFixed(2) ?? "N/A"}
                                            </span>
                                          )}
                                        </div>
                                      ))
                                    ) : (
                                      <div className="text-muted-foreground">—</div>
                                    )}
                                  </div>
                                </div>
                                <div className="mt-2 text-xs text-muted-foreground">
                                  红盘率 {(c.red_ratio * 100).toFixed(0)}% | 高开&gt;2% {c.hh_n}只 | 竞价涨停开 {c.limit_up_open_n ?? 0}只 | 竞价额 {(c.total_amount / 10000).toFixed(0)}万
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Volume tab */
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <h2 className="font-semibold">竞价量排行</h2>
            <span className="text-xs text-muted-foreground">{stocks.length} 只</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">竞价量（手）</th>
                  <th className="px-3 py-2 text-right font-medium">竞价额</th>
                  <th className="px-3 py-2 text-right font-medium">价格</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s, i) => (
                  <tr key={s.code} className="border-t hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                    <td className="px-3 py-2 font-mono">{s.code}</td>
                    <td className="px-3 py-2">{s.name}</td>
                    <td className="px-3 py-2 text-right font-medium">{Math.round(s.auction_vol / 100).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">{s.auction_amount ? (s.auction_amount / 10000).toFixed(0) + "万" : "-"}</td>
                    <td className="px-3 py-2 text-right">{s.auction_price?.toFixed(2)}</td>
                  </tr>
                ))}
                {stocks.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

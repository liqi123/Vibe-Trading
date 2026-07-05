import { useEffect, useState } from "react";
import { RefreshCw, Zap, TrendingUp, TrendingDown, BarChart3, Calendar } from "lucide-react";

interface AuctionStat {
  count: number; total_vol: number; total_amount: number; avg_ratio: number;
}

interface AuctionStock {
  code: string; name: string; auction_vol: number; auction_amount: number;
  auction_ratio: number; auction_price: number; open_price: number;
  total_vol: number; total_amount: number;
}

interface DateInfo {
  date: string; count: number; total_vol: number; avg_ratio: number;
}

interface CompareStock {
  code: string; name: string; vol_today: number; vol_prev: number;
  vol_chg: number; vol_pct: number; price_today: number; ratio_today: number;
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

export function AuctionBoard() {
  const [dates, setDates] = useState<DateInfo[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [stocks, setStocks] = useState<AuctionStock[]>([]);
  const [leaders, setLeaders] = useState<AuctionStock[]>([]);
  const [stats, setStats] = useState<AuctionStat | null>(null);
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [tab, setTab] = useState<"volume" | "ratio" | "compare">("volume");
  const [compareData, setCompareData] = useState<{ date1: string; date2: string; gainers: CompareStock[]; losers: CompareStock[]; increase: number; decrease: number; total: number } | null>(null);

  const fetchDates = async () => {
    try {
      const res = await fetch("/tools/auction/dates");
      if (res.ok) {
        const data = await res.json();
        setDates(data.dates || []);
        if (data.dates?.length > 0 && !selectedDate) {
          setSelectedDate(data.dates[0].date);
        }
      }
    } catch (e) { console.error("fetch dates", e); }
  };

  const fetchDateData = async (date: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/tools/auction/latest?date=${encodeURIComponent(date)}&limit=100`);
      if (res.ok) {
        const data = await res.json();
        setStocks(data.stocks || []);
        setLeaders(data.leaders || []);
        setStats(data.stats || null);
      }
    } catch (e) { console.error("fetch date data", e); }
    finally { setLoading(false); }
  };

  const fetchCompare = async () => {
    if (dates.length < 2) return;
    const d1 = selectedDate || dates[0].date;
    const d2 = dates.find(d => d.date !== d1)?.date || dates[1]?.date;
    if (!d2) return;
    setLoading(true);
    try {
      const res = await fetch(`/tools/auction/compare?date1=${encodeURIComponent(d1)}&date2=${encodeURIComponent(d2)}&top=30`);
      if (res.ok) {
        setCompareData(await res.json());
      }
    } catch (e) { console.error("fetch compare", e); }
    finally { setLoading(false); }
  };

  const handleCollect = async () => {
    setCollecting(true);
    try {
      await fetch("/tools/auction/collect", { method: "POST" });
    } catch (e) { console.error("handle collect", e); }
    finally { setCollecting(false); }
  };

  useEffect(() => { fetchDates(); }, []);

  useEffect(() => {
    if (selectedDate) {
      if (tab === "compare") fetchCompare();
      else fetchDateData(selectedDate);
    }
  }, [selectedDate, tab]);

  const sortedByRatio = [...stocks].sort((a, b) => (b.auction_ratio || 0) - (a.auction_ratio || 0));

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
          { key: "ratio" as const, label: "竞价占比排行", icon: TrendingUp },
          { key: "compare" as const, label: "竞价对比", icon: TrendingDown },
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
                    <th className="px-3 py-2 text-right font-medium">今日竞价量</th>
                    <th className="px-3 py-2 text-right font-medium">昨日竞价量</th>
                    <th className="px-3 py-2 text-right font-medium">变化量</th>
                    <th className="px-3 py-2 text-right font-medium">变化%</th>
                    <th className="px-3 py-2 text-right font-medium">竞价价</th>
                  </tr>
                </thead>
                <tbody>
                  {compareData.gainers.map((s, i) => (
                    <tr key={s.code} className="border-t hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{s.code}</td>
                      <td className="px-3 py-2">{s.name}</td>
                      <td className="px-3 py-2 text-right">{s.vol_today.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{s.vol_prev.toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${volClass(s.vol_chg)}`}>
                        {s.vol_chg > 0 ? "+" : ""}{s.vol_chg.toLocaleString()}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${volClass(s.vol_pct)}`}>
                        {s.vol_pct >= 999 ? "NEW" : `${s.vol_pct >= 0 ? "+" : ""}${s.vol_pct.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-2 text-right">{s.price_today?.toFixed(2)}</td>
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
                    <th className="px-3 py-2 text-right font-medium">今日竞价量</th>
                    <th className="px-3 py-2 text-right font-medium">昨日竞价量</th>
                    <th className="px-3 py-2 text-right font-medium">变化量</th>
                    <th className="px-3 py-2 text-right font-medium">变化%</th>
                    <th className="px-3 py-2 text-right font-medium">竞价价</th>
                  </tr>
                </thead>
                <tbody>
                  {compareData.losers.map((s, i) => (
                    <tr key={s.code} className="border-t hover:bg-muted/30">
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-mono">{s.code}</td>
                      <td className="px-3 py-2">{s.name}</td>
                      <td className="px-3 py-2 text-right">{s.vol_today.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{s.vol_prev.toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${volClass(s.vol_chg)}`}>
                        {s.vol_chg > 0 ? "+" : ""}{s.vol_chg.toLocaleString()}
                      </td>
                      <td className={`px-3 py-2 text-right font-medium ${volClass(s.vol_pct)}`}>
                        {s.vol_pct >= 999 ? "NEW" : `${s.vol_pct >= 0 ? "+" : ""}${s.vol_pct.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-2 text-right">{s.price_today?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        /* Volume / Ratio tab */
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center justify-between">
            <h2 className="font-semibold">
              {tab === "volume" ? "竞价量排行（全部）" : "竞价占比排行（全部）"}
            </h2>
            <span className="text-xs text-muted-foreground">{stocks.length} 只</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">竞价量</th>
                  <th className="px-3 py-2 text-right font-medium">竞价额</th>
                  <th className="px-3 py-2 text-right font-medium">竞价占比</th>
                  <th className="px-3 py-2 text-right font-medium">竞价价</th>
                  <th className="px-3 py-2 text-right font-medium">开盘价</th>
                  <th className="px-3 py-2 text-right font-medium">总量</th>
                </tr>
              </thead>
              <tbody>
                {(tab === "volume" ? stocks : sortedByRatio).map((s, i) => (
                  <tr key={s.code} className="border-t hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                    <td className="px-3 py-2 font-mono">{s.code}</td>
                    <td className="px-3 py-2">{s.name}</td>
                    <td className="px-3 py-2 text-right font-medium">{s.auction_vol.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">{s.auction_amount ? (s.auction_amount / 10000).toFixed(0) + "万" : "-"}</td>
                    <td className={`px-3 py-2 text-right font-medium ${(s.auction_ratio || 0) > 15 ? "text-red-600" : ""}`}>
                      {s.auction_ratio ? s.auction_ratio.toFixed(1) + "%" : "-"}
                    </td>
                    <td className="px-3 py-2 text-right">{s.auction_price?.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{s.open_price?.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{s.total_vol?.toLocaleString()}</td>
                  </tr>
                ))}
                {stocks.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* High Ratio Leaders */}
      {leaders.length > 0 && tab !== "compare" && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <h2 className="font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-orange-500" />
              竞价占比 &gt; 15% 的活跃股
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">排名</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-right font-medium">竞价占比</th>
                  <th className="px-3 py-2 text-right font-medium">竞价量</th>
                  <th className="px-3 py-2 text-right font-medium">竞价价</th>
                  <th className="px-3 py-2 text-right font-medium">开盘价</th>
                </tr>
              </thead>
              <tbody>
                {leaders.map((s, i) => (
                  <tr key={s.code} className="border-t hover:bg-muted/30">
                    <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                    <td className="px-3 py-2 font-mono">{s.code}</td>
                    <td className="px-3 py-2">{s.name}</td>
                    <td className="px-3 py-2 text-right font-medium text-red-600">{s.auction_ratio?.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right">{s.auction_vol.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">{s.auction_price?.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{s.open_price?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

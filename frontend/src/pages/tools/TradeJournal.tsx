import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

interface Trade {
  date: string;
  code: string;
  name: string;
  action: string;
  price: number;
  shares: number;
  reason?: string;
}

interface Stats {
  total: number;
  closed: number;
  winning: number;
  losing: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

interface GroupStat { n: number; win_rate: number; avg_pnl_pct: number; total_pnl?: number }
interface PatternCard { pattern: string; n: number; win_rate: number; avg_pnl_pct: number; total_pnl: number }
interface DisciplineIssue { date: string; code: string; name: string; rule: string; detail: string }
interface PendingItem { date: string; code: string; name: string; pnl_pct: number | null; days_since: number | null; exit_date?: string; exit_reason?: string }
interface Xirr { available?: boolean; reason?: string; xirr?: number; n_trades?: number }
interface JournalReport {
  by_emotion?: Record<string, GroupStat>; by_board?: Record<string, GroupStat>;
  discipline?: DisciplineIssue[]; pending_review?: PendingItem[];
  patterns?: PatternCard[]; xirr?: Xirr; error?: string;
}

const fmtPct1 = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v.toFixed(d)}%`);

export function TradeJournal() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [weekly, setWeekly] = useState("");
  const [report, setReport] = useState<JournalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"trades" | "stats" | "weekly" | "report">("trades");

  const fetchData = async () => {
    setLoading(true);
    try {
      const [jData, wData, rData] = await Promise.all([
        api.tools.get<any>("/journal?days=90"),
        api.tools.get<any>("/journal/weekly"),
        api.tools.get<any>("/journal/report?days=90"),
      ]);
      setTrades(jData.trades || []);
      setStats(jData.stats || null);
      setWeekly(wData.report || "");
      setReport(rData);
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">交易日志</h1>
          <p className="text-sm text-muted-foreground mt-1">交易记录与统计分析</p>
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />刷新
        </button>
      </div>

      <div className="flex gap-2 border-b">
        {(["trades", "stats", "weekly", "report"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}>
            {t === "trades" ? "交易记录" : t === "stats" ? "统计数据" : t === "weekly" ? "周报" : "复盘报告"}
          </button>
        ))}
      </div>

      {tab === "trades" && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium">日期</th>
                  <th className="px-4 py-2 text-left font-medium">代码</th>
                  <th className="px-4 py-2 text-left font-medium">名称</th>
                  <th className="px-4 py-2 text-left font-medium">操作</th>
                  <th className="px-4 py-2 text-right font-medium">价格</th>
                  <th className="px-4 py-2 text-right font-medium">数量</th>
                  <th className="px-4 py-2 text-left font-medium">原因</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">暂无记录</td></tr>
                ) : trades.map((t, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="px-4 py-2 text-muted-foreground">{t.date}</td>
                    <td className="px-4 py-2 font-mono text-xs">{t.code}</td>
                    <td className="px-4 py-2">{t.name}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.action === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                      }`}>
                        {t.action === "buy" ? "买入" : "卖出"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">{t.price?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right">{t.shares}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{t.reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "stats" && stats && (
        <div className="grid gap-4 md:grid-cols-4">
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">总交易</div>
            <p className="text-2xl font-bold">{stats.total}</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">胜率</div>
            <p className="text-2xl font-bold text-red-600">{stats.win_rate ? (stats.win_rate * 100).toFixed(1) : 0}%</p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">总盈亏</div>
            <p className={`text-2xl font-bold ${(stats.total_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
              {(stats.total_pnl || 0) >= 0 ? "+" : ""}{(stats.total_pnl || 0).toFixed(2)}
            </p>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            <div className="text-sm text-muted-foreground mb-1">平均盈亏</div>
            <p className={`text-2xl font-bold ${(stats.avg_pnl || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
              {(stats.avg_pnl || 0).toFixed(2)}
            </p>
          </div>
        </div>
      )}

      {tab === "weekly" && (
        <div className="border rounded-lg bg-card p-5">
          <pre className="text-sm whitespace-pre-wrap font-mono">{weekly || "暂无周报数据"}</pre>
        </div>
      )}

      {tab === "report" && (
        <div className="space-y-4">
          {report?.error && <div className="border rounded-lg bg-card p-4 text-sm text-destructive">{report.error}</div>}

          {/* XIRR + 纪律/复查概览 */}
          <div className="grid gap-4 md:grid-cols-3">
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">已平仓组合 XIRR（年化）</div>
              {report?.xirr?.available ? (
                <p className={`text-2xl font-bold ${(report.xirr.xirr ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                  {fmtPct1(((report.xirr.xirr ?? 0) * 100))}
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">{report?.xirr?.reason ?? "—"}</p>
              )}
              {report?.xirr?.available && <p className="mt-1 text-xs text-muted-foreground">{report.xirr.n_trades} 笔</p>}
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">纪律违规</div>
              <p className={`text-2xl font-bold ${(report?.discipline?.length ?? 0) > 0 ? "text-destructive" : ""}`}>
                {report?.discipline?.length ?? 0}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {[...new Set((report?.discipline ?? []).map((d) => d.rule))].join(" · ") || "无"}
              </p>
            </div>
            <div className="border rounded-lg p-4 bg-card">
              <div className="text-sm text-muted-foreground mb-1">待复查（平仓未评分）</div>
              <p className={`text-2xl font-bold ${(report?.pending_review?.length ?? 0) > 0 ? "text-amber-600" : ""}`}>
                {report?.pending_review?.length ?? 0}
              </p>
            </div>
          </div>

          {/* 按情绪档 / 按板位 */}
          <div className="grid gap-4 md:grid-cols-2">
            {[{ title: "对账 · 按入场日情绪档", rows: report?.by_emotion }, { title: "对账 · 按入场日板位", rows: report?.by_board }].map((g) => (
              <div key={g.title} className="border rounded-lg bg-card p-4">
                <p className="text-sm font-medium mb-2">{g.title}</p>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      {["组", "n", "胜率", "均盈亏%", "累计盈亏"].map((h) => <th key={h} className="py-1.5 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(g.rows ?? {}).length === 0 ? (
                      <tr><td colSpan={5} className="py-3 text-center text-xs text-muted-foreground">暂无已平仓样本</td></tr>
                    ) : Object.entries(g.rows ?? {}).map(([k, s]) => (
                      <tr key={k} className="border-b last:border-0">
                        <td className="py-1.5">{k}</td>
                        <td className="py-1.5 font-mono">{s.n}</td>
                        <td className="py-1.5 font-mono">{fmtPct1(s.win_rate)}</td>
                        <td className={`py-1.5 font-mono ${s.avg_pnl_pct >= 0 ? "text-red-600" : "text-green-600"}`}>{s.avg_pnl_pct.toFixed(1)}</td>
                        <td className={`py-1.5 font-mono ${(s.total_pnl ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                          {(s.total_pnl ?? 0).toFixed(0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          {/* 模式卡 */}
          <div className="border rounded-lg bg-card p-4">
            <p className="text-sm font-medium mb-2">模式卡（情绪档 × 板位，n≥2 才成卡）</p>
            {(report?.patterns ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">暂无成卡模式（已平仓样本不足或未带情绪快照）</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    {["模式", "n", "胜率", "均盈亏%", "累计盈亏"].map((h) => <th key={h} className="py-1.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(report?.patterns ?? []).map((p) => (
                    <tr key={p.pattern} className="border-b last:border-0">
                      <td className="py-1.5 font-medium">{p.pattern}</td>
                      <td className="py-1.5 font-mono">{p.n}</td>
                      <td className="py-1.5 font-mono">{fmtPct1(p.win_rate)}</td>
                      <td className={`py-1.5 font-mono ${p.avg_pnl_pct >= 0 ? "text-red-600" : "text-green-600"}`}>{p.avg_pnl_pct.toFixed(1)}</td>
                      <td className={`py-1.5 font-mono ${p.total_pnl >= 0 ? "text-red-600" : "text-green-600"}`}>{p.total_pnl.toFixed(0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* 纪律违规明细 + 待复查明细 */}
          <div className="grid gap-4 md:grid-cols-2">
            <div className="border rounded-lg bg-card p-4">
              <p className="text-sm font-medium mb-2">纪律违规明细</p>
              {(report?.discipline ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">无违规</p>
              ) : (
                <ul className="space-y-1 text-xs">
                  {(report?.discipline ?? []).map((d, i) => (
                    <li key={i} className="flex gap-2 border-b last:border-0 py-1.5">
                      <span className="font-mono text-muted-foreground">{d.date}</span>
                      <span>{d.name}</span>
                      <span className="text-destructive font-medium">{d.rule}</span>
                      <span className="text-muted-foreground ml-auto">{d.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="border rounded-lg bg-card p-4">
              <p className="text-sm font-medium mb-2">待复查清单</p>
              {(report?.pending_review ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">全部已评分</p>
              ) : (
                <ul className="space-y-1 text-xs">
                  {(report?.pending_review ?? []).map((p, i) => (
                    <li key={i} className="flex gap-2 border-b last:border-0 py-1.5">
                      <span className="font-mono text-muted-foreground">{p.exit_date || p.date}</span>
                      <span>{p.name}</span>
                      <span className={`font-mono ${(p.pnl_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(1)}%` : "—"}
                      </span>
                      <span className="text-muted-foreground ml-auto">{p.exit_reason || "—"} · {p.days_since ?? "?"}天前</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

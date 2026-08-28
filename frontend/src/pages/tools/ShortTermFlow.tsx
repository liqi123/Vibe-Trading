import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlarmClock,
  BarChart3,
  Bell,
  Brain,
  CalendarClock,
  Crosshair,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  Sun,
  Target,
  Wallet,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AuctionSentiment } from "./AuctionSentiment";

interface Position {
  code: string;
  name: string;
  buy_price: number;
  current_price: number;
  shares: number;
  pnl_pct: number;
  stop?: number | null;
  E?: number | null;
  take_profit?: number | null;
}
interface Alert {
  portfolio?: string;
  code: string;
  name: string;
  reason: string;
  price: number;
  threshold?: number;
}
interface Portfolio {
  name: string;
  strategy: string;
  return_pct: number;
  total: number;
  cash: number;
  positions: Position[];
  alerts: Alert[];
}
interface FlowStatus {
  ok: boolean;
  date: string;
  is_today: boolean;
  auction: { exists: boolean; count: number; collect_time?: string | null };
  pre: {
    fear_greedy?: { date: string; afgi: number; state: string } | null;
    prev_bizday: string;
    prev_review: boolean;
    prev_vibe: boolean;
  };
  holdings: Portfolio[];
  post: { review: boolean; vibe: boolean };
}

const chip = (ok: boolean) =>
  ok
    ? "px-2 py-0.5 text-xs rounded-full bg-green-500/15 text-green-600 border border-green-500/30"
    : "px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground border";

function SectionHeader({ icon: Icon, title, time, color, right }: { icon: any; title: string; time: string; color: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Icon className={`h-5 w-5 ${color}`} />
      <h2 className="font-semibold text-base">{title}</h2>
      <span className="text-xs text-muted-foreground">{time}</span>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

function HoldingsPanel({ portfolios, onReload }: { portfolios: Portfolio[]; onReload: () => void }) {
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ alerts: Alert[]; wecom_pushed: boolean } | null>(null);

  const key = (pf: string, code: string) => `${pf}::${code}`;

  const setTarget = async (portfolio: string, code: string) => {
    const k = key(portfolio, code);
    const price = parseFloat(targets[k]);
    if (!price) return;
    setSaving(k);
    try {
      await api.tools.post(`/flow/target`, { code, price, portfolio });
      setTargets((t) => ({ ...t, [k]: "" }));
      await onReload();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setSaving(null);
    }
  };

  const runStops = async () => {
    setRunning(true);
    try {
      const res = await api.tools.post<{ ok: boolean; alerts: Alert[]; wecom_pushed: boolean; holdings: Portfolio[] }>(`/flow/stops`);
      setResult({ alerts: res.alerts ?? [], wecom_pushed: !!res.wecom_pushed });
      await onReload();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={runStops}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          运行止盈/止损检查
        </button>
        <Link to="/paper-trading" className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
          <Wallet className="h-3.5 w-3.5" /> 模拟盘详情
        </Link>
      </div>

      {result && (
        <div className={cn("rounded-lg border p-3 text-sm", result.alerts.length ? "bg-orange-500/5 border-orange-500/30" : "bg-muted/40")}>
          {result.alerts.length ? (
            <>
              <p className="font-medium flex items-center gap-1.5 text-orange-600">
                <Bell className="h-4 w-4" /> {result.alerts.length} 条止盈/止损告警{result.wecom_pushed && "（已推企业微信）"}
              </p>
              <ul className="mt-1 space-y-1 text-xs">
                {result.alerts.map((a, i) => (
                  <li key={i} className="text-muted-foreground">
                    {a.portfolio} · {a.name}({a.code})：{a.reason}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-muted-foreground text-xs">检查完成：无止盈/止损告警{result.wecom_pushed && "（已推企业微信）"}</p>
          )}
        </div>
      )}

      {portfolios.length === 0 && <p className="text-xs text-muted-foreground">无模拟盘数据</p>}

      <div className="grid gap-3 lg:grid-cols-2">
        {portfolios.map((pf) => (
          <div key={pf.strategy} className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold text-sm">{pf.name}</h3>
              <span className={cn("text-xs tabular-nums font-medium", pf.return_pct >= 0 ? "text-danger" : "text-success")}>
                {pf.return_pct >= 0 ? "+" : ""}
                {pf.return_pct.toFixed(2)}%
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              总资产 {pf.total.toLocaleString()} · 现金 {pf.cash.toLocaleString()} · 持仓 {pf.positions.length} 只
            </p>
            {pf.positions.length === 0 ? (
              <p className="text-xs text-muted-foreground">空仓</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground border-b">
                    <th className="py-1.5 pr-2 font-medium">标的</th>
                    <th className="py-1.5 pr-2 font-medium">现价/成本</th>
                    <th className="py-1.5 pr-2 font-medium">盈亏</th>
                    <th className="py-1.5 font-medium">止盈价</th>
                  </tr>
                </thead>
                <tbody>
                  {pf.positions.map((p) => {
                    const k = key(pf.strategy, p.code);
                    return (
                      <tr key={p.code} className="border-b last:border-0">
                        <td className="py-1.5 pr-2">
                          <span className="font-medium">{p.name}</span>
                          <span className="text-muted-foreground ml-1">{p.code}</span>
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {p.current_price.toFixed(2)}
                          <span className="text-muted-foreground"> / {p.buy_price.toFixed(2)}</span>
                        </td>
                        <td className={cn("py-1.5 pr-2 tabular-nums", p.pnl_pct >= 0 ? "text-danger" : "text-success")}>
                          {p.pnl_pct >= 0 ? "+" : ""}
                          {p.pnl_pct.toFixed(2)}%
                        </td>
                        <td className="py-1.5">
                          <div className="flex items-center gap-1">
                            <input
                              type="number"
                              step="0.01"
                              placeholder={p.take_profit ? String(p.take_profit) : "—"}
                              value={targets[k] ?? ""}
                              onChange={(e) => setTargets((t) => ({ ...t, [k]: e.target.value }))}
                              className="w-20 px-1.5 py-0.5 text-xs border rounded bg-background"
                            />
                            <button
                              onClick={() => setTarget(pf.strategy, p.code)}
                              disabled={saving === k}
                              className="px-2 py-0.5 text-xs border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                            >
                              {saving === k ? <Loader2 className="h-3 w-3 animate-spin" /> : <Target className="h-3 w-3" />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {pf.alerts.length > 0 && (
              <div className="space-y-1">
                {pf.alerts.map((a, i) => (
                  <p key={i} className="text-xs text-orange-600">
                    ● {a.name}：{a.reason}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ShortTermFlow() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [status, setStatus] = useState<FlowStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.tools.get<FlowStatus>(`/flow/status?date=${date}`);
      setStatus(res);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    load();
  }, [load]);

  const collectAuction = async () => {
    setCollecting(true);
    try {
      await api.tools.post(`/auction/collect`);
      await load();
    } catch (e: any) {
      alert(e?.message ?? String(e));
    } finally {
      setCollecting(false);
    }
  };

  const alertsCount = (status?.holdings ?? []).reduce((n, pf) => n + pf.alerts.length, 0);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Crosshair className="h-5 w-5 text-violet-500" /> 短线全流程
        </h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-2 py-1 text-sm border rounded-md bg-background"
          />
          <button onClick={() => load()} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
          </button>
        </div>
      </div>

      {/* 一句话串联 */}
      <p className="text-xs text-muted-foreground -mt-2">
        盘前选好票 → 竞价后豆包/DeepSeek+多源综合出方案 → 盘中验资金→验合力→验龙头 → 执行计划内那一笔 → 持仓达标止盈止损即推企业微信 → 盘后复盘核验 → 明天继续。
      </p>

      {loading && !status ? (
        <div className="border rounded-lg p-12 text-center text-muted-foreground">
          <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin opacity-50" />
          <p className="text-xs">加载全流程状态…</p>
        </div>
      ) : error && !status ? (
        <div className="border rounded-lg p-12 text-center text-sm text-destructive">加载失败: {error}</div>
      ) : status ? (
        <>
          {/* 阶段状态条 */}
          <div className="flex flex-wrap gap-2 text-xs">
            <span className={cn(chip(true), "flex items-center gap-1")}>
              <Sun className="h-3.5 w-3.5" /> 盘前：{status.pre.fear_greedy?.state ?? "—"}
            </span>
            <span className={chip(status.auction.exists)}>
              <BarChart3 className="h-3.5 w-3.5 inline mr-0.5" /> 竞价：{status.auction.exists ? `${status.auction.count} 条` : "无"}
            </span>
            <span className={chip(alertsCount === 0)}>
              <Bell className="h-3.5 w-3.5 inline mr-0.5" /> 持仓告警 {alertsCount} 条
            </span>
            <span className={chip(status.post.review)}>
              <FileText className="h-3.5 w-3.5 inline mr-0.5" /> 复盘：{status.post.review ? "已生成" : "无"}
            </span>
            <span className={chip(status.post.vibe)}>
              <Brain className="h-3.5 w-3.5 inline mr-0.5" /> 明日预演：{status.post.vibe ? "已生成" : "无"}
            </span>
          </div>

          {/* 盘前 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={Sun} title="盘前准备" time="阶段〇 · T-1盘后 + 09:15 前" color="text-orange-500" />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">恐惧贪婪指数（最近）</p>
                <p className="mt-1 text-lg font-bold">
                  {status.pre.fear_greedy ? `${status.pre.fear_greedy.afgi} · ${status.pre.fear_greedy.state}` : "—"}
                </p>
                <p className="text-xs text-muted-foreground">{status.pre.fear_greedy?.date ?? "未更新"}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">
                  昨日复盘（{status.pre.prev_bizday}）
                </p>
                <p className={cn("mt-1 text-sm font-medium", status.pre.prev_review ? "text-green-600" : "text-muted-foreground")}>
                  {status.pre.prev_review ? "已生成" : "未生成"}
                </p>
                <Link to="/daily-review" className="mt-1 text-xs text-primary hover:underline inline-block">
                  查看复盘 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">vibe 明日预演（{status.pre.prev_bizday}）</p>
                <p className={cn("mt-1 text-sm font-medium", status.pre.prev_vibe ? "text-green-600" : "text-muted-foreground")}>
                  {status.pre.prev_vibe ? "已生成" : "未生成"}
                </p>
                <Link to="/vibe-review" className="mt-1 text-xs text-primary hover:underline inline-block">
                  查看明日关注点 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">盘前待办</p>
                <ul className="mt-1 text-xs text-muted-foreground space-y-1">
                  <li>· 外围（美股/韩日/新闻）+ 板块三问（高潮/超跌/预期差）</li>
                  <li>· 豆包盘前①：定周期/主线/候选池</li>
                  <li>· 每票定买点·止盈价·止损价</li>
                </ul>
              </div>
            </div>
          </div>

          {/* 竞价后 + 盘中 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader
              icon={AlarmClock}
              title="竞价后 + 盘中验证"
              time="阶段一~四 · 09:25-10:00"
              color="text-emerald-500"
              right={
                <div className="flex flex-wrap gap-2">
                  {status.is_today && (
                    <button
                      onClick={collectAuction}
                      disabled={collecting}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      {collecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
                      采集竞价
                    </button>
                  )}
                  <Link to="/auction-board" className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors">
                    <Brain className="h-3.5 w-3.5" /> 竞价看板：发豆包/多源综合
                  </Link>
                </div>
              }
            />
            <p className="text-xs text-muted-foreground">
              竞价后把「单问版 + 阶段②」并发发豆包并做多源综合，用下面四阶段规则验证资金态度与主线合力：
            </p>
            <AuctionSentiment date={date} />
          </div>

          {/* 持仓监控 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={Target} title="持仓监控" time="贯穿 · 止盈/止损达标即推企业微信" color="text-rose-500" />
            <HoldingsPanel portfolios={status.holdings} onReload={load} />
          </div>

          {/* 盘后 */}
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <SectionHeader icon={CalendarClock} title="盘后复盘与明日预演" time="阶段五 · 15:00 后" color="text-blue-500" />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">复盘报告（{status.date}）</p>
                <p className={cn("mt-1 text-sm font-medium", status.post.review ? "text-green-600" : "text-muted-foreground")}>
                  {status.post.review ? "已生成" : "未生成"}
                </p>
                <Link to="/daily-review" className="mt-1 text-xs text-primary hover:underline inline-block">
                  查看复盘 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">vibe 明日预演（{status.date}）</p>
                <p className={cn("mt-1 text-sm font-medium", status.post.vibe ? "text-green-600" : "text-muted-foreground")}>
                  {status.post.vibe ? "已生成" : "未生成"}
                </p>
                <Link to="/vibe-review" className="mt-1 text-xs text-primary hover:underline inline-block">
                  查看明日关注点 →
                </Link>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">验证闭环</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  早晨豆包/多源结论 vs 收盘结果打勾核验，落 verification/reports，次日复盘自动对账
                </p>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
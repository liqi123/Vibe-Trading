import { useState, useEffect, useRef, useCallback } from "react";
import {
  Play, Loader2, AlertCircle, RefreshCw, Gauge, Flame, BarChart3, Globe, TrendingUp, FileText, ListChecks, Users,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

// A股红涨绿跌（与 MarketReview 约定一致）
const pctColor = (p: number) => (p > 0 ? "text-danger" : p < 0 ? "text-success" : "text-muted-foreground");
const fmt = (v: number | null | undefined, digits = 2) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: digits }));
const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(1)} 亿`);
const localDate = () => {
  const x = new Date();
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};

interface AnalystCard { key: string; title: string; tag: string; html: string }
interface VerifyItem { metric: string; label: string; direction: string; reason?: string; base_value?: number | null; unit?: string }
interface FocusBlock { text?: string; verification_items?: VerifyItem[] }
interface ReviewPayload {
  date?: string; analysts?: AnalystCard[]; focus?: FocusBlock; focus_md?: string;
  sentiment_report?: string; capital_report?: string; theme_report?: string;
  dragon_tiger_report?: string; leader_report?: string; macro_sector_report?: string;
  warnings?: string[];
}

interface SentimentBlock { up: number; down: number; flat: number; zt: number; zt_real: number; dt: number; dt_real: number; breadth: string; speculation: string; date: string }
interface SectorFlow { name: string; pct: number; net: number; inflow: number | null; outflow: number | null; firms: number }
interface EmotionBlock { date: string; zt_count: number; dt_count: number; zb_count: number; max_boards: number; lianban_count: number; seal_rate: number | null; break_rate: number | null; promotion_rate: number | null }
interface TurnoverStock { code: string; name: string; price: number | null; pct: number | null; amount: number | null; mcap: number | null; industry: string }
interface GlobalIndex { key: string; name: string; region: string; price: number | null; change_pct: number | null }
interface OverseasBlock { available: boolean; indices: { name: string; price: number; change_pct: number; session: string }[]; mag7: { name: string; price: number; change_pct: number; session: string; ticker: string }[]; us_label?: string; hk_label?: string }
interface FirstBoardStock { code: string; name: string; price: number; pct: number; amount: number; float_cap: number; industry: string; seal_time: string; break_count: number }
interface FirstBoardBlock { date: string; total_zt: number; first_count: number; stocks: FirstBoardStock[]; reason_note?: string }
interface WeeklyDay { date: string; limit_up: number; broken_rate: number; highest_consec: number; leader: { code: string; name: string; boards: number; sector: string } | null }
interface WeeklyBlock { days: WeeklyDay[] }

const ANALYST_ORDER = ["sentiment", "capital", "theme", "dragon_tiger", "leader"];

export function VibeReview() {
  const [date, setDate] = useState(localDate());
  const [dates, setDates] = useState<string[]>([]);
  const [payload, setPayload] = useState<ReviewPayload | null>(null);
  const [payloadLoaded, setPayloadLoaded] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);

  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 盘面数据
  const [overview, setOverview] = useState<SentimentBlock | null>(null);
  const [sectors, setSectors] = useState<SectorFlow[]>([]);
  const [emotion, setEmotion] = useState<EmotionBlock | null>(null);
  const [turnover, setTurnover] = useState<TurnoverStock[]>([]);
  const [globals, setGlobals] = useState<GlobalIndex[]>([]);
  const [overseas, setOverseas] = useState<OverseasBlock | null>(null);
  const [firstboard, setFirstboard] = useState<FirstBoardBlock | null>(null);
  const [weekly, setWeekly] = useState<WeeklyBlock | null>(null);

  const loadReview = useCallback(async (d: string) => {
    try {
      const r = await api.tools.get<{ payload: ReviewPayload | null }>(`/vibe/review?date=${d}`);
      setPayload(r.payload);
    } catch {
      setPayload(null);
    } finally {
      setPayloadLoaded(true);
    }
  }, []);

  useEffect(() => {
    api.tools.get<{ dates: string[] }>("/vibe/review/dates").then((r) => setDates(r.dates || [])).catch(() => {});
  }, []);

  useEffect(() => {
    api.tools.get<any>("/vibe/market-data").then((r) => {
      setOverview(r.overview?.sentiment ?? null);
      setSectors(r.overview?.sectors ?? []);
      setEmotion(r.emotion ?? null);
      setTurnover(r.turnover_top?.stocks ?? []);
      setGlobals(r.global_indices ?? []);
      setOverseas(r.overseas?.available ? r.overseas : null);
    }).catch(() => {});
    api.tools.get<FirstBoardBlock>("/vibe/firstboard").then(setFirstboard).catch(() => {});
    api.tools.get<WeeklyBlock>("/vibe/weekly").then(setWeekly).catch(() => {});
    loadReview(date);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const runReview = async () => {
    setRunErr(null);
    setOutput("启动中...");
    setRunning(true);
    try {
      const { task_id } = await api.tools.post<{ task_id: string }>("/vibe/review/run", { date });
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.tools.get<{ content: string }>(`/vibe/review/status/${task_id}`);
          setOutput(s.content);
          if (s.content.includes("执行完成") || s.content.includes("exit=")) {
            if (pollRef.current) clearInterval(pollRef.current);
            setRunning(false);
            loadReview(date);
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setRunning(false);
          setRunErr("状态读取失败");
        }
      }, 3000);
    } catch (e: any) {
      setRunning(false);
      setRunErr(e?.message ?? String(e));
    }
  };

  const analysts: AnalystCard[] = payload?.analysts?.length
    ? payload.analysts
    : ANALYST_ORDER.map((k) => ({ key: k, title: k, tag: "", html: "" })).filter((a) => (payload as any)?.[`${a.key}_report`]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold flex items-center gap-2"><Users className="h-5 w-5" /> 短线多智能体复盘</h1>
        <input
          type="date"
          value={date}
          max={localDate()}
          onChange={(e) => { setDate(e.target.value); setPayload(null); setPayloadLoaded(false); loadReview(e.target.value); }}
          className="ml-2 px-2 py-1 text-sm border rounded-md bg-background"
        />
        <button
          onClick={runReview}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          {running ? "复盘运行中" : "运行复盘"}
        </button>
        {dates.length > 0 && (
          <select
            value=""
            onChange={(e) => { if (e.target.value) { setDate(e.target.value); loadReview(e.target.value); } }}
            className="px-2 py-1 text-sm border rounded-md bg-background"
          >
            <option value="">历史复盘 ▾</option>
            {dates.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        )}
        {runErr && <span className="text-xs text-destructive">{runErr}</span>}
      </div>

      {running && output && (
        <div className="border rounded-lg p-3 bg-muted/20">
          <p className="mb-1.5 text-[11px] text-muted-foreground">引擎输出（约 5-10 分钟，页面可停留查看）</p>
          <pre className="max-h-56 overflow-auto text-[11px] leading-relaxed whitespace-pre-wrap">{output}</pre>
        </div>
      )}

      {/* 1. 复盘正文 */}
      <div>
        <div className="mb-3 flex items-center gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><FileText className="h-4 w-4" /> 多智能体复盘 {payload?.date ? <span className="text-[11px] text-muted-foreground/50">{payload.date}</span> : null}</h3>
          {payload && <button onClick={() => loadReview(date)} className="ml-auto flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}
        </div>
        {!payloadLoaded ? (
          <div className="border rounded-lg p-8 text-center text-muted-foreground"><Loader2 className="h-5 w-5 mx-auto mb-2 animate-spin opacity-50" /></div>
        ) : payload ? (
          <div className="space-y-4">
            {analysts.length > 0 && (
              <div className="grid gap-3 md:grid-cols-2">
                {analysts.map((a) => (
                  <div key={a.key} className="border rounded-lg p-4 bg-card">
                    <p className="mb-2 text-xs font-semibold text-muted-foreground">{a.title}</p>
                    <div className="text-[13px] leading-relaxed prose prose-sm dark:prose-invert max-w-none" dangerouslySetInnerHTML={{ __html: a.html }} />
                  </div>
                ))}
              </div>
            )}
            {payload.focus?.verification_items && payload.focus.verification_items.length > 0 && (
              <div className="border rounded-lg p-4 bg-card">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground"><ListChecks className="h-3.5 w-3.5" /> 明日验证条件（次日复盘自动对账）</p>
                <div className="flex flex-wrap gap-2">
                  {payload.focus.verification_items.map((it, i) => (
                    <span key={i} className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                      <span className="font-medium">{it.label ?? it.metric}</span>
                      <span className={cn(it.direction === "上升" ? "text-danger" : it.direction === "下降" ? "text-success" : "text-muted-foreground")}>{it.direction}</span>
                      {it.base_value != null && <span className="text-muted-foreground">基准 {fmt(it.base_value)}{it.unit ?? ""}</span>}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {payload.focus_md && (
              <div className="border rounded-lg p-4 bg-card">
                <p className="mb-2 text-xs font-semibold text-muted-foreground">明日关注点</p>
                <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{payload.focus_md}</ReactMarkdown>
                </div>
              </div>
            )}
            {!analysts.length && !payload.focus_md && !payload.focus?.verification_items?.length && (
              <div className="border rounded-lg p-8 text-center text-muted-foreground">
                <AlertCircle className="h-6 w-6 mx-auto mb-2 opacity-40" />
                <p className="text-sm">该日期未生成可用复盘（AI 环节可能未跑通），可点「运行复盘」重跑</p>
              </div>
            )}
          </div>
        ) : (
          <div className="border rounded-lg p-8 text-center text-muted-foreground">
            <FileText className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">该日期还没有复盘，点右上「运行复盘」生成（约 5-10 分钟，需 LLM 凭据）</p>
          </div>
        )}
      </div>

      {/* 2. 市场情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Gauge className="h-4 w-4" /> 市场情绪</h3>
        {overview?.date && <span className="ml-auto text-[11px] text-muted-foreground/50">{overview.date}</span>}
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {overview ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {[{ k: "大盘宽度", v: overview.breadth }, { k: "题材投机", v: overview.speculation }].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-4">
                  <p className="text-xs text-muted-foreground">{m.k}</p>
                  <p className="mt-1 text-2xl font-bold text-primary">{m.v}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              {[
                { k: "涨停", v: overview.zt, cls: "text-danger" },
                { k: "涨停(真实)", v: overview.zt_real, cls: "text-danger" },
                { k: "跌停", v: overview.dt, cls: "text-success" },
                { k: "跌停(真实)", v: overview.dt_real, cls: "text-success" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                  <p className="truncate text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
          </>
        ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
      </div>

      {/* 3. 短线情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 短线情绪</h3>
        {emotion?.date && <span className="ml-auto text-[11px] text-muted-foreground/50">{emotion.date}</span>}
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {emotion ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "涨停", v: `${emotion.zt_count}`, cls: "text-danger" },
                { k: "跌停", v: `${emotion.dt_count}`, cls: "text-success" },
                { k: "炸板", v: `${emotion.zb_count}`, cls: "text-muted-foreground" },
                { k: "最高连板", v: `${emotion.max_boards} 板`, cls: "text-primary" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                { k: "封板率", v: emotion.seal_rate, strong: true },
                { k: "炸板率", v: emotion.break_rate, strong: false },
                { k: "晋级率", v: emotion.promotion_rate, strong: true },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
                    {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                  </p>
                </div>
              ))}
            </div>
          </>
        ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
      </div>

      {/* 4. 板块资金 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><BarChart3 className="h-4 w-4" /> 板块资金（净流入 TOP）</h3>
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {sectors.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["板块", "涨跌%", "净流入", "流入", "流出", "家数"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {sectors.slice(0, 15).map((s) => (
                  <tr key={s.name} className="border-b border-border/30">
                    <td className="px-2 py-2"><span className="font-medium">{s.name}</span></td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
                    <td className="px-2 py-2 font-mono text-danger">{s.net.toFixed(1)} 亿</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.inflow == null ? "—" : `${s.inflow.toFixed(0)} 亿`}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.outflow == null ? "—" : `${s.outflow.toFixed(0)} 亿`}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
      </div>

      {/* 5. 成交额 TOP20 + 首板 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><TrendingUp className="h-4 w-4" /> 成交额 TOP20</h3>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            {turnover.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["#", "名称", "现价", "涨跌%", "成交额"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {turnover.slice(0, 20).map((s, i) => (
                      <tr key={s.code} className="border-b border-border/30">
                        <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                        <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                        <td className="px-2 py-2 font-mono">{fmt(s.price)}</td>
                        <td className={cn("px-2 py-2 font-mono", pctColor(s.pct ?? 0))}>{s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}</td>
                        <td className="px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
          </div>
        </div>
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 首板池</h3>
            {firstboard?.date && <span className="text-[11px] text-muted-foreground/50">{firstboard.date} · 涨停 {firstboard.total_zt} · 首板 {firstboard.first_count}</span>}
          </div>
          <div className="border rounded-lg p-4 bg-card">
            {firstboard?.stocks?.length ? (
              <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "封板时间", "炸板", "成交额"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {firstboard.stocks.map((s) => (
                      <tr key={s.code} className="border-b border-border/30">
                        <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                        <td className="px-2 py-2 font-mono">{s.seal_time}</td>
                        <td className="px-2 py-2 font-mono">{s.break_count}</td>
                        <td className="px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="p-4 text-center text-sm text-muted-foreground">{firstboard ? "暂无数据" : "数据加载中..."}</p>}
          </div>
        </div>
      </div>

      {/* 6. 全球 + 外围 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 全球指数</h3>
          </div>
          <div className="border rounded-lg p-4 bg-card">
            {globals.length > 0 ? (
              <table className="w-full text-sm">
                <tbody>
                  {globals.map((g) => (
                    <tr key={g.key} className="border-b border-border/30 last:border-0">
                      <td className="px-2 py-2"><span className="font-medium">{g.name}</span> <span className="text-xs text-muted-foreground/50">{g.region}</span></td>
                      <td className="px-2 py-2 text-right font-mono">{fmt(g.price)}</td>
                      <td className={cn("px-2 py-2 text-right font-mono", pctColor(g.change_pct ?? 0))}>{g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
          </div>
        </div>
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 隔夜外围</h3>
            {overseas?.us_label && <span className="text-[11px] text-muted-foreground/50">{overseas.us_label} · {overseas.hk_label}</span>}
          </div>
          <div className="border rounded-lg p-4 bg-card">
            {overseas ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["标的", "价格", "涨跌%", "交易日"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {[...overseas.indices, ...overseas.mag7].map((m, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="px-2 py-2 font-medium">{m.name}</td>
                        <td className="px-2 py-2 font-mono">{m.price}</td>
                        <td className={cn("px-2 py-2 font-mono", pctColor(m.change_pct))}>{m.change_pct > 0 ? "+" : ""}{m.change_pct}%</td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">{m.session}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中...</p>}
          </div>
        </div>
      </div>

      {/* 7. 近5日热度 + 龙头谱系 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><TrendingUp className="h-4 w-4" /> 近 5 交易日热度与龙头谱系</h3>
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {weekly?.days?.length ? (
          <div className="grid gap-2 sm:grid-cols-5">
            {weekly.days.map((d) => (
              <div key={d.date} className="rounded-lg bg-muted/20 p-3">
                <p className="text-[11px] text-muted-foreground">{d.date}</p>
                <p className="mt-1 text-sm">涨停 <span className="font-mono font-bold text-danger">{d.limit_up}</span></p>
                <p className="text-xs text-muted-foreground">炸板率 {(d.broken_rate * 100).toFixed(0)}% · 最高 {d.highest_consec} 板</p>
                {d.leader && (
                  <p className="mt-1.5 text-xs truncate"><span className="font-medium">{d.leader.name}</span> <span className="text-muted-foreground">{d.leader.boards}板·{d.leader.sector}</span></p>
                )}
              </div>
            ))}
          </div>
        ) : <p className="p-4 text-center text-sm text-muted-foreground">数据加载中（首次约 40s）...</p>}
      </div>
    </div>
  );
}

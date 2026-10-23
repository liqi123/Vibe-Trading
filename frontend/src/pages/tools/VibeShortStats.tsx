import { useState, useRef, useCallback, useEffect } from "react";
import {
  Loader2, RefreshCw, AlertCircle, ChevronDown, ChevronRight, Shuffle, Zap, History, GitCompare, FileText, Activity, Layers, Radar,
  Inbox, Newspaper, CalendarDays, BookOpen, Search, Percent,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const fmt = (v: number | null | undefined, digits = 2) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: digits }));

interface ThemeRow {
  tag: string; state: string; counts: (number | null)[]; ranks: (number | null)[];
  days_present: number; latest_count: number | null; latest_rank: number | null;
  rank_delta: number | null; peak_count: number; leaders: string[];
}
interface ThemeRotation { available: boolean; reason?: string; dates?: string[]; themes?: ThemeRow[]; theme_total?: number; missing_dates?: { date: string; reason: string }[] }
interface SampleAgg { n: number; avg_ret?: number; median_ret?: number; win_rate?: number; promote_rate?: number | null; deep_loss_rate?: number }
type SampleGroup = { group: string } & SampleAgg
interface ZtSamples {
  available: boolean; reason?: string; end?: string; sample?: number; days?: number;
  overall?: SampleAgg; by_board?: SampleGroup[]; by_seal?: SampleGroup[]; by_emotion?: SampleGroup[];
  skipped?: { date: string; reason: string }[];
}
interface EmotionSeriesRow { date: string; limit_up?: number | null; highest_consec?: number | null; broken_rate?: number | null; promotion_1to2?: number | null; [k: string]: any }
interface EmotionHistory { available: boolean; reason?: string; series?: EmotionSeriesRow[]; readings?: { key: string; label: string; unit: string }[]; note?: string }
interface StructureItem {
  key: string; label: string; unit?: string; available: boolean;
  recent_median_text?: string; base_median_text?: string; shifted?: boolean; hotter?: boolean | null;
}
interface StructureChange {
  available: boolean; reason?: string; date?: string; items?: StructureItem[];
  shifted_count?: number; recent_window?: string[]; base_window?: string[];
}
interface WeeklyAi { available: boolean; reason?: string; markdown?: string; week_end?: string; dates?: string[] }
interface EmotionPathPoint {
  timepoint: string; captured_at?: string; zt_count?: number | null; zb_count?: number | null; dt_count?: number | null;
  max_boards?: number | null; lianban_count?: number | null; seal_rate?: number | null; promotion_rate?: number | null; prev_median?: number | null;
}
interface EmotionPath {
  available: boolean; reason?: string; error?: string; date?: string; timepoints?: string[];
  captured?: string[]; missed?: string[]; points?: EmotionPathPoint[]; note?: string;
}
interface AuctionTier {
  tier: string; sample: number; expected: number; median: number | null; avg: number | null;
  up_count: number; down_count: number; up_rate: number | null; deep_loss_5: number;
}
interface AuctionStock { code: string; name: string; boards: number; sector: string; tier: string; pct: number | null }
interface AuctionStrength {
  available: boolean; reason?: string; error?: string; date?: string; sample_date?: string; basis?: string;
  overall?: { sample: number; expected: number; median: number | null; avg: number | null; up_count: number; down_count: number; up_rate: number | null; deep_loss_5: number; coverage_rate: number | null };
  tiers?: AuctionTier[]; top_boards?: number;
  top?: { code: string; name: string; boards: number; sector: string; pct: number | null }[];
  stocks?: AuctionStock[]; notes?: string[];
}
interface LadderStock { code: string; name: string; sector: string; seal_time: string }
interface LadderTier { boards: number; count: number; stocks?: LadderStock[] }
interface StatBlock { available?: boolean; reason?: string; [k: string]: any }
interface TodayEmotion {
  available: boolean; reason?: string; error?: string; date?: string;
  summary?: { zt?: number; zb?: number; dt?: number; max_boards?: number };
  ladder?: LadderTier[]; ladder_note?: string;
  ladder_gap?: StatBlock; seal_quality?: StatBlock; consec_premium?: StatBlock;
  money_effect?: StatBlock; cycle?: StatBlock;
}
interface MoverEvent { code: string; name: string; kind: string; time: string; pct: number; price: number; limit_price?: number }
interface Movers {
  available: boolean; reason?: string; error?: string; as_of?: string; threshold?: number;
  minutes?: number; n_codes?: number; movers?: MoverEvent[]; failed?: string[]; note?: string;
}
interface PoolPos {
  code: string; name: string; category: string; price: number | null; prev_close: number | null;
  pct: number | null; cost_price: number | null; pnl_pct: number | null; note: string;
  stop_loss: number | null; take_profit: number | null;
}
interface PoolHist {
  closed_n: number; median_xirr_pct: number | null; win_n: number; note?: string;
  per_lot: { code?: string; name?: string; buy_date?: string; sell_date?: string; hold_days?: number | null; pnl_pct?: number; sell_reason?: string; xirr?: number | null }[];
}
interface PoolData {
  available: boolean; reason?: string; error?: string; positions?: PoolPos[];
  counts?: Record<string, number>; quotes_as_of?: string; history?: PoolHist;
}
interface NewsItem { title?: string; source?: string; date?: string; url?: string; snippet?: string }
interface NewsRes {
  available: boolean; reason?: string; error?: string; n_news?: number; note?: string;
  items?: { code: string; name?: string; news?: NewsItem[]; error?: string }[];
}
interface ResearchRes {
  available: boolean; reason?: string; error?: string; code?: string; n?: number; note?: string;
  reports?: { title: string; org: string; author: string; date: string; rating: string; eps_this: string; pe_this: string; pdf: string }[];
}
interface CalRow {
  code: string; name?: string; date: string; period?: string;
  shares_yi?: number; mv_yi?: number | null; float_pct?: number; kind?: string; holders?: number;
}
interface CalendarRes {
  available: boolean; reason?: string; error?: string; as_of?: string; days?: number; cached?: boolean;
  disclosure?: { period?: string; rows?: CalRow[] }; unlock?: CalRow[]; failed?: string[]; note?: string;
}
interface TaskLatest { available: boolean; reason?: string; error?: string; markdown?: string; code?: string; generated_at?: string }

const STATE_CLS: Record<string, string> = {
  "首现": "text-danger", "连续": "text-danger", "回流": "text-warning",
  "退潮": "text-success", "消退": "text-success", "缺席": "text-muted-foreground",
};
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function Section({ title, icon, open, onToggle, children, extra }: {
  title: string; icon: React.ReactNode; open: boolean; onToggle: () => void; children: React.ReactNode; extra?: React.ReactNode;
}) {
  return (
    <div className="border rounded-lg bg-card">
      <button onClick={onToggle} className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-muted/30 transition-colors">
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        {icon}
        <span className="text-sm font-semibold">{title}</span>
        <span className="ml-auto flex items-center gap-2" onClick={(e) => e.stopPropagation()}>{extra}</span>
      </button>
      {open && <div className="border-t px-4 py-3">{children}</div>}
    </div>
  );
}

function Err({ msg }: { msg: string }) {
  return <p className="p-4 text-center text-sm text-destructive flex items-center justify-center gap-1.5"><AlertCircle className="h-4 w-4" /> {msg}</p>;
}
function Loading() {
  return <p className="p-4 text-center text-sm text-muted-foreground flex items-center justify-center gap-1.5"><Loader2 className="h-4 w-4 animate-spin opacity-50" /> 加载中…</p>;
}
function Empty({ msg }: { msg: string }) {
  return <p className="p-4 text-center text-sm text-muted-foreground">{msg}</p>;
}

function BlockCard({ title, b, rows }: {
  title: string; b?: StatBlock; rows: [string, (x: any) => React.ReactNode][];
}) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold text-muted-foreground">{title}</p>
      {b?.available ? (
        <table className="w-full text-xs">
          <tbody>
            {rows.map(([k, f]) => (
              <tr key={k} className="border-b border-border/30 last:border-0">
                <td className="py-1 pr-2 whitespace-nowrap text-muted-foreground">{k}</td>
                <td className="py-1 text-right font-mono">{f(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="text-xs text-muted-foreground">{b?.reason ?? "不可用"}</p>}
    </div>
  );
}

const KIND_CLS: Record<string, string> = { rapid_up: "text-danger", rapid_down: "text-success", seal: "text-danger", broken: "text-warning" };
const KIND_LABEL: Record<string, string> = { rapid_up: "急拉", rapid_down: "急跌", seal: "封板", broken: "开板" };
const CAT_LABEL: Record<string, string> = { holding: "持仓", observation: "观察", candidate: "候选" };

type DeskTab = "news" | "research" | "digest" | "debate";

function StockResearchDesk() {
  const [code, setCode] = useState("");
  const [tab, setTab] = useState<DeskTab>("news");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [news, setNews] = useState<NewsRes | null>(null);
  const [research, setResearch] = useState<ResearchRes | null>(null);
  const [tasks, setTasks] = useState<Record<string, TaskLatest | null>>({});
  const [taskOut, setTaskOut] = useState("");
  const [taskRun, setTaskRun] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const loadNews = async () => {
    setLoading(true); setErr("");
    try { setNews(await api.tools.get<NewsRes>(`/vibe/stats/news?codes=${encodeURIComponent(code)}&size=5`)); }
    catch (e: any) { setNews(null); setErr(e?.message ?? String(e)); }
    finally { setLoading(false); }
  };
  const loadResearch = async () => {
    setLoading(true); setErr("");
    try { setResearch(await api.tools.get<ResearchRes>(`/vibe/stats/research?code=${encodeURIComponent(code)}`)); }
    catch (e: any) { setResearch(null); setErr(e?.message ?? String(e)); }
    finally { setLoading(false); }
  };
  const loadCachedTask = async (k: DeskTab) => {
    const r = await api.tools.get<TaskLatest>(`/vibe/stats/task/${k}/latest?code=${encodeURIComponent(code)}`);
    setTasks((p) => ({ ...p, [k]: r }));
  };
  const pickTab = (t: DeskTab) => {
    setTab(t); setErr("");
    if (t === "news" && !news) loadNews();
    else if (t === "research" && !research) loadResearch();
    else if ((t === "digest" || t === "debate") && !tasks[t]) loadCachedTask(t).catch(() => setTasks((p) => ({ ...p, [t]: null })));
  };
  const runTask = async () => {
    if (!code.trim()) { setErr("先填股票代码（sh600519 / 600519 / sz301618 均可）"); return; }
    setTaskRun(true); setTasks((p) => ({ ...p, [tab]: null })); setTaskOut("启动中…"); setErr("");
    try {
      const { task_id } = await api.tools.post<{ task_id: string }>(`/vibe/stats/task/${tab}`, { code: code.trim(), name: "" });
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.tools.get<{ content: string }>(`/vibe/stats/task/${tab}/${task_id}`);
          setTaskOut(s.content);
          if (s.content.includes("执行完成") || s.content.includes("exit=")) {
            if (pollRef.current) clearInterval(pollRef.current);
            setTaskRun(false);
            loadCachedTask(tab).catch(() => {});
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setTaskRun(false);
        }
      }, 4000);
    } catch (e: any) {
      setTaskRun(false);
      setTaskOut(`错误: ${e?.message ?? e}`);
    }
  };

  const tabs: { k: DeskTab; label: string }[] = [
    { k: "news", label: "资讯" }, { k: "research", label: "研报" },
    { k: "digest", label: "AI 深挖" }, { k: "debate", label: "多空辩论" },
  ];
  const cur = tasks[tab] ?? null;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="代码 sh600519 / 600519"
            className="h-7 w-40 rounded border bg-background px-2 font-mono text-xs" />
        </div>
        {tabs.map((t) => (
          <button key={t.k} onClick={() => pickTab(t.k)}
            className={cn("rounded px-2 py-1 text-[11px] border", tab === t.k ? "bg-muted font-semibold" : "hover:bg-muted/50 text-muted-foreground")}>
            {t.label}
          </button>
        ))}
        {(tab === "digest" || tab === "debate") && (
          <button onClick={runTask} disabled={taskRun}
            className="flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-muted disabled:opacity-50">
            {taskRun ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
            {taskRun ? "生成中（1-3 分钟）" : tab === "digest" ? "生成深挖" : "生成辩论"}
          </button>
        )}
        {(tab === "news" || tab === "research") && (
          <button onClick={tab === "news" ? loadNews : loadResearch} disabled={loading}
            className="flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-muted disabled:opacity-50">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} 重新加载
          </button>
        )}
      </div>
      {err && <p className="mb-2 text-xs text-destructive">{err}</p>}
      {loading ? <Loading /> : null}

      {tab === "news" && news && !loading && (
        news.available ? (
          <div className="space-y-3">
            {(news.items ?? []).map((it) => (
              <div key={it.code}>
                <p className="mb-1 text-xs font-semibold text-muted-foreground">{it.name || it.code}{it.error ? ` · ${it.error}` : ""}</p>
                {(it.news ?? []).length ? (
                  <ul className="space-y-1">
                    {(it.news ?? []).map((n, i) => (
                      <li key={i} className="text-xs">
                        {n.url ? <a href={n.url} target="_blank" rel="noreferrer" className="hover:underline">{n.title}</a> : n.title}
                        <span className="ml-1.5 text-[11px] text-muted-foreground">{n.source}{n.date ? ` ${n.date}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-xs text-muted-foreground">无结果</p>}
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground">{news.note}</p>
          </div>
        ) : <Empty msg={news.reason ?? news.error ?? "不可用"} />
      )}

      {tab === "research" && research && !loading && (
        research.available ? (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["日期", "标题", "机构", "评级", "今年EPS", "今年PE", "PDF"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(research.reports ?? []).map((r, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-mono text-xs whitespace-nowrap">{r.date}</td>
                      <td className="px-2 py-1.5">{r.title}</td>
                      <td className="px-2 py-1.5 text-xs whitespace-nowrap">{r.org}</td>
                      <td className="px-2 py-1.5 text-xs">{r.rating || "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.eps_this || "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.pe_this || "—"}</td>
                      <td className="px-2 py-1.5 text-xs">{r.pdf ? <a href={r.pdf} target="_blank" rel="noreferrer" className="hover:underline">打开</a> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">{research.note}</p>
          </div>
        ) : <Empty msg={research.reason ?? research.error ?? "不可用"} />
      )}

      {tab === "digest" && !loading && (
        taskRun ? <pre className="max-h-40 overflow-auto rounded bg-muted/20 p-2 text-[11px] whitespace-pre-wrap">{taskOut}</pre>
          : cur?.available && cur.markdown ? (
            <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
              <p className="mb-2 text-xs text-muted-foreground">{cur.code} · 生成于 {cur.generated_at}</p>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{cur.markdown}</ReactMarkdown>
            </div>
          ) : <Empty msg={cur?.reason ?? "尚未生成，填代码点「生成深挖」（约 1-3 分钟）"} />
      )}

      {tab === "debate" && !loading && (
        taskRun ? <pre className="max-h-40 overflow-auto rounded bg-muted/20 p-2 text-[11px] whitespace-pre-wrap">{taskOut}</pre>
          : cur?.available && cur.markdown ? (
            <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
              <p className="mb-2 text-xs text-muted-foreground">{cur.code} · 生成于 {cur.generated_at}</p>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{cur.markdown}</ReactMarkdown>
            </div>
          ) : <Empty msg={cur?.reason ?? "尚未生成，填代码点「生成辩论」（约 1-3 分钟）"} />
      )}
    </div>
  );
}

export function VibeShortStats() {
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const loadedRef = useRef<Record<string, boolean>>({});

  const [rotation, setRotation] = useState<ThemeRotation | null>(null);
  const [samples, setSamples] = useState<ZtSamples | null>(null);
  const [history, setHistory] = useState<EmotionHistory | null>(null);
  const [structure, setStructure] = useState<StructureChange | null>(null);
  const [weeklyAi, setWeeklyAi] = useState<WeeklyAi | null>(null);
  const [epath, setEpath] = useState<EmotionPath | null>(null);
  const [epathMsg, setEpathMsg] = useState("");
  const [auction, setAuction] = useState<AuctionStrength | null>(null);
  const [todayEmo, setTodayEmo] = useState<TodayEmotion | null>(null);
  const [movers, setMovers] = useState<Movers | null>(null);
  const [pool, setPool] = useState<PoolData | null>(null);
  const [calendar, setCalendar] = useState<CalendarRes | null>(null);
  const [sector, setSector] = useState<TaskLatest | null>(null);
  const [secRunning, setSecRunning] = useState(false);
  const [secOutput, setSecOutput] = useState("");
  const secPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [wkRunning, setWkRunning] = useState(false);
  const [wkOutput, setWkOutput] = useState("");
  const [captureMsg, setCaptureMsg] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadSection = useCallback(async (key: string) => {
    if (loadedRef.current[key]) return;
    loadedRef.current[key] = true;
    setLoading((p) => ({ ...p, [key]: true }));
    try {
      if (key === "rotation") setRotation(await api.tools.get<ThemeRotation>("/vibe/stats/theme-rotation?days=5&top=20"));
      else if (key === "samples") setSamples(await api.tools.get<ZtSamples>("/vibe/stats/zt-samples?days=20"));
      else if (key === "history") setHistory(await api.tools.get<EmotionHistory>("/vibe/stats/emotion-history?days=30"));
      else if (key === "structure") setStructure(await api.tools.get<StructureChange>("/vibe/stats/structure-change"));
      else if (key === "weekly") setWeeklyAi(await api.tools.get<WeeklyAi>("/vibe/stats/weekly-ai"));
      else if (key === "epath") setEpath(await api.tools.get<EmotionPath>("/vibe/stats/emotion-path"));
      else if (key === "auction") setAuction(await api.tools.get<AuctionStrength>("/vibe/stats/auction-strength"));
      else if (key === "today") setTodayEmo(await api.tools.get<TodayEmotion>("/vibe/stats/today-emotion"));
      else if (key === "movers") setMovers(await api.tools.get<Movers>("/vibe/stats/movers?threshold=1.5"));
      else if (key === "pool") setPool(await api.tools.get<PoolData>("/vibe/stats/pool"));
      else if (key === "calendar") setCalendar(await api.tools.get<CalendarRes>("/vibe/stats/calendar?days=120"));
      else if (key === "sector") setSector(await api.tools.get<TaskLatest>("/vibe/stats/task/sector/latest"));
    } catch (e: any) {
      const msg = e?.message ?? String(e);
      if (key === "rotation") setRotation({ available: false, reason: msg });
      else if (key === "samples") setSamples({ available: false, reason: msg });
      else if (key === "history") setHistory({ available: false, reason: msg });
      else if (key === "structure") setStructure({ available: false, reason: msg });
      else if (key === "weekly") setWeeklyAi({ available: false, reason: msg });
      else if (key === "epath") setEpath({ available: false, reason: msg });
      else if (key === "auction") setAuction({ available: false, reason: msg });
      else if (key === "today") setTodayEmo({ available: false, reason: msg });
      else if (key === "movers") setMovers({ available: false, reason: msg });
      else if (key === "pool") setPool({ available: false, reason: msg });
      else if (key === "calendar") setCalendar({ available: false, reason: msg });
      else if (key === "sector") setSector({ available: false, reason: msg });
    } finally {
      setLoading((p) => ({ ...p, [key]: false }));
    }
  }, []);

  const toggle = (key: string) => {
    if (open === key) { setOpen(null); return; }
    setOpen(key);
    loadSection(key);
  };

  const reload = (key: string) => {
    loadedRef.current[key] = false;
    if (key === "rotation") setRotation(null);
    else if (key === "samples") setSamples(null);
    else if (key === "history") setHistory(null);
    else if (key === "structure") setStructure(null);
    else if (key === "weekly") setWeeklyAi(null);
    else if (key === "epath") setEpath(null);
    else if (key === "auction") setAuction(null);
    else if (key === "today") setTodayEmo(null);
    else if (key === "movers") setMovers(null);
    else if (key === "pool") setPool(null);
    else if (key === "calendar") setCalendar(null);
    else if (key === "sector") setSector(null);
    loadSection(key);
  };

  // 盯盘异动：展开期间每 60s 静默刷新（不闪 loading）
  useEffect(() => {
    if (open !== "movers" || !movers?.available) return;
    const id = setInterval(async () => {
      try {
        const r = await api.tools.get<Movers>("/vibe/stats/movers?threshold=1.5");
        if (r?.available) setMovers(r);
      } catch { /* 网络抖动保留旧数据 */ }
    }, 60000);
    return () => clearInterval(id);
  }, [open, movers?.available]);

  const capturePath = async () => {
    setEpathMsg("采集中…");
    try {
      const r = await api.tools.post<any>("/vibe/stats/emotion-path/capture", {});
      setEpathMsg(r.skipped ? `${r.timepoint} 已采过（首采为准）` : r.ok ? `已采集 ${r.timepoint}` : `跳过：${r.reason ?? r.error ?? "未知"}`);
      reload("epath");
    } catch (e: any) {
      setEpathMsg(`失败: ${e?.message ?? e}`);
    }
  };

  const capture = async () => {
    setCaptureMsg("回补中…");
    try {
      const r = await api.tools.post<any>("/vibe/stats/capture?days=25", {});
      setCaptureMsg(`已缓存 ${r.cached ?? "?"} 天` + (r.failed?.length ? `，失败 ${r.failed.length}` : ""));
    } catch (e: any) {
      setCaptureMsg(`失败: ${e?.message ?? e}`);
    }
  };

  const runWeeklyAi = async () => {
    setWkRunning(true);
    setWkOutput("启动中…");
    try {
      const { task_id } = await api.tools.post<{ task_id: string }>("/vibe/stats/weekly-ai/run", { date: "" });
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.tools.get<{ content: string }>(`/vibe/stats/weekly-ai/status/${task_id}`);
          setWkOutput(s.content);
          if (s.content.includes("执行完成") || s.content.includes("exit=")) {
            if (pollRef.current) clearInterval(pollRef.current);
            setWkRunning(false);
            reload("weekly");
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setWkRunning(false);
        }
      }, 3000);
    } catch (e: any) {
      setWkRunning(false);
      setWkOutput(`错误: ${e?.message ?? e}`);
    }
  };

  const runSectorAi = async () => {
    setSecRunning(true);
    setSecOutput("启动中…");
    try {
      const { task_id } = await api.tools.post<{ task_id: string }>("/vibe/stats/task/sector", {});
      secPollRef.current = setInterval(async () => {
        try {
          const s = await api.tools.get<{ content: string }>(`/vibe/stats/task/sector/${task_id}`);
          setSecOutput(s.content);
          if (s.content.includes("执行完成") || s.content.includes("exit=")) {
            if (secPollRef.current) clearInterval(secPollRef.current);
            setSecRunning(false);
            reload("sector");
          }
        } catch {
          if (secPollRef.current) clearInterval(secPollRef.current);
          setSecRunning(false);
        }
      }, 4000);
    } catch (e: any) {
      setSecRunning(false);
      setSecOutput(`错误: ${e?.message ?? e}`);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Shuffle className="h-4 w-4" /> 短线统计（题材轮动 · 涨停样本 · 情绪历史 · 结构变化 · 周报）</h3>
      </div>

      {/* 题材轮动 */}
      <Section title="题材轮动（近 5 交易日）" icon={<Shuffle className="h-4 w-4 text-muted-foreground" />} open={open === "rotation"} onToggle={() => toggle("rotation")}
        extra={<button onClick={() => reload("rotation")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.rotation ? <Loading /> : !rotation ? <Empty msg="点击展开加载" /> : !rotation.available ? <Err msg={rotation.reason ?? "不可用"} /> : (
          <>
            <div className="mb-2 text-xs text-muted-foreground">
              窗口 {rotation.dates?.join(" ~ ")} · 共 {rotation.theme_total} 题材
              {rotation.missing_dates?.length ? ` · 缺数日 ${rotation.missing_dates.map((m) => m.date).join(",")}` : ""}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["题材", "状态", "今日涨停", "今日名次", "在场", "峰值", "近5日各日涨停数", "龙头"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(rotation.themes ?? []).map((t) => (
                    <tr key={t.tag} className="border-b border-border/30">
                      <td className="px-2 py-2"><span className="font-medium">{t.tag}</span></td>
                      <td className={cn("px-2 py-2", STATE_CLS[t.state] ?? "text-muted-foreground")}>{t.state}</td>
                      <td className="px-2 py-2 font-mono font-bold text-danger">{t.latest_count ?? "—"}</td>
                      <td className="px-2 py-2 font-mono">{t.latest_rank ?? "—"}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{t.days_present}天</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{t.peak_count}</td>
                      <td className="px-2 py-2 font-mono text-xs text-muted-foreground">{t.counts.map((c) => c ?? "-").join(" / ")}</td>
                      <td className="px-2 py-2 text-xs">{t.leaders.join("、") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      {/* 涨停样本 */}
      <Section title="涨停样本（近 20 日 · 昨日涨停股次日表现）" icon={<Zap className="h-4 w-4 text-muted-foreground" />} open={open === "samples"} onToggle={() => toggle("samples")}
        extra={<button onClick={() => reload("samples")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.samples ? <Loading /> : !samples ? <Empty msg="点击展开加载（首次含回补，约 30s）" /> : !samples.available ? <Err msg={samples.reason ?? "不可用"} /> : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                { k: "样本数", v: fmt(samples.sample, 0) },
                { k: "均值%", v: fmt(samples.overall?.avg_ret) },
                { k: "中位%", v: fmt(samples.overall?.median_ret) },
                { k: "胜率", v: pct(samples.overall?.win_rate) },
                { k: "深亏≤-5%", v: pct(samples.overall?.deep_loss_rate) },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{m.k}</p>
                  <p className="mt-0.5 font-mono text-sm font-bold">{m.v}</p>
                </div>
              ))}
            </div>
            <div className="grid gap-3 lg:grid-cols-3">
              {[
                { title: "按板位", rows: samples.by_board },
                { title: "按封板时段", rows: samples.by_seal },
                { title: "按入场日情绪", rows: samples.by_emotion },
              ].map((g) => (
                <div key={g.title}>
                  <p className="mb-1.5 text-xs font-semibold text-muted-foreground">{g.title}</p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-[11px] text-muted-foreground">
                        {["组", "n", "均值%", "胜率", "晋级率"].map((h) => <th key={h} className="px-1.5 py-1.5 font-medium">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {(g.rows ?? []).map((r) => (
                        <tr key={r.group} className="border-b border-border/30">
                          <td className="px-1.5 py-1.5">{r.group}</td>
                          <td className="px-1.5 py-1.5 font-mono">{r.n}</td>
                          <td className={cn("px-1.5 py-1.5 font-mono", (r.avg_ret ?? 0) > 0 ? "text-danger" : (r.avg_ret ?? 0) < 0 ? "text-success" : "")}>{fmt(r.avg_ret)}</td>
                          <td className="px-1.5 py-1.5 font-mono">{pct(r.win_rate)}</td>
                          <td className="px-1.5 py-1.5 font-mono text-muted-foreground">{pct(r.promote_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
            {samples.skipped?.length ? <p className="mt-2 text-[11px] text-muted-foreground">缺数日：{samples.skipped.map((s) => s.date).join(",")}</p> : null}
          </>
        )}
      </Section>

      {/* 情绪历史 */}
      <Section title="情绪历史（近 30 日读数序列）" icon={<History className="h-4 w-4 text-muted-foreground" />} open={open === "history"} onToggle={() => toggle("history")}
        extra={<button onClick={capture} className="text-[11px] px-2 py-1 border rounded hover:bg-muted">回补缓存</button>}>
        {loading.history ? <Loading /> : !history ? <Empty msg="点击展开加载" /> : !history.available ? <Err msg={history.reason ?? "不可用"} /> : (
          <>
            {captureMsg && <p className="mb-2 text-[11px] text-muted-foreground">{captureMsg}</p>}
            <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["日期", "涨停", "最高板", "炸板率", "1进2"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[...(history.series ?? [])].reverse().map((row) => (
                    <tr key={row.date} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-mono text-xs">{row.date}</td>
                      <td className="px-2 py-1.5 font-mono font-bold text-danger">{row.limit_up ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{row.highest_consec ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{pct(row.broken_rate)}</td>
                      <td className="px-2 py-1.5 font-mono">{pct(row.promotion_1to2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">{history.note ?? "仅覆盖已有缓存的交易日"}</p>
          </>
        )}
      </Section>

      {/* 结构变化 */}
      <Section title="结构变化（近 10 日 vs 前 20 日）" icon={<GitCompare className="h-4 w-4 text-muted-foreground" />} open={open === "structure"} onToggle={() => toggle("structure")}
        extra={<button onClick={() => reload("structure")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.structure ? <Loading /> : !structure ? <Empty msg="点击展开加载" /> : !structure.available ? <Err msg={structure.reason ?? "不可用"} /> : (
          <>
            <div className="mb-2 text-xs text-muted-foreground">
              基准 {structure.base_window?.join("~")} → 近期 {structure.recent_window?.join("~")} · 移位 {structure.shifted_count} 项
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["读数", "基准中位", "近10日中位", "变化"].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {(structure.items ?? []).map((it) => (
                  <tr key={it.key} className="border-b border-border/30">
                    <td className="px-2 py-2">{it.label}</td>
                    {it.available ? (
                      <>
                        <td className="px-2 py-2 font-mono text-muted-foreground">{it.base_median_text}</td>
                        <td className="px-2 py-2 font-mono">{it.recent_median_text}</td>
                        <td className={cn("px-2 py-2", it.shifted ? (it.hotter ? "text-danger font-semibold" : "text-success font-semibold") : "text-muted-foreground")}>
                          {it.shifted ? (it.hotter ? "变热" : "变冷") : "—"}
                        </td>
                      </>
                    ) : (
                      <td colSpan={3} className="px-2 py-2 text-muted-foreground">缓存不足</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Section>

      {/* 竞价强弱 */}
      <Section title="竞价强弱（昨日涨停 · 09:25 竞价）" icon={<Percent className="h-4 w-4 text-muted-foreground" />} open={open === "auction"} onToggle={() => toggle("auction")}
        extra={<button onClick={() => reload("auction")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.auction ? <Loading /> : !auction ? <Empty msg="点击展开加载" /> : !auction.available ? <Err msg={auction.reason ?? auction.error ?? "不可用"} /> : (
          <>
            <div className="mb-2 text-xs text-muted-foreground">
              {auction.date} 09:25 · 样本 = {auction.sample_date} 涨停 {auction.overall?.expected ?? "?"} 只 · {auction.basis}
            </div>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                { k: "中位数%（多数人的体感）", v: fmt(auction.overall?.median) },
                { k: "均值%", v: fmt(auction.overall?.avg) },
                { k: "高开占比", v: pct(auction.overall?.up_rate) },
                { k: "低开超5%（只）", v: auction.overall?.deep_loss_5 ?? "—" },
                { k: "覆盖率", v: pct(auction.overall?.coverage_rate) },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{m.k}</p>
                  <p className="mt-0.5 font-mono text-sm font-bold">{m.v}</p>
                </div>
              ))}
            </div>
            <p className="mb-1.5 text-xs font-semibold text-muted-foreground">分昨日板位 —— 首板和高位板的竞价含义完全不同</p>
            <div className="mb-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-[11px] text-muted-foreground">
                    {["板位", "取到/预期", "中位%", "均值%", "高开占比", "低开超5%"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-1.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(auction.tiers ?? []).map((t) => (
                    <tr key={t.tier} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-semibold">{t.tier}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{t.sample}/{t.expected}</td>
                      <td className={cn("px-2 py-1.5 font-mono font-semibold", (t.median ?? 0) > 0 ? "text-danger" : (t.median ?? 0) < 0 ? "text-success" : "")}>{fmt(t.median)}</td>
                      <td className={cn("px-2 py-1.5 font-mono", (t.avg ?? 0) > 0 ? "text-danger" : (t.avg ?? 0) < 0 ? "text-success" : "")}>{fmt(t.avg)}</td>
                      <td className="px-2 py-1.5 font-mono">{pct(t.up_rate)}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{t.deep_loss_5}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(auction.top ?? []).length ? (
              <div className="mb-3 flex items-start gap-2 text-sm">
                <span className="shrink-0 font-semibold text-muted-foreground">最高标（{auction.top_boards} 板）</span>
                <div className="flex flex-wrap gap-1.5">
                  {auction.top!.map((s) => (
                    <span key={s.code} className="rounded bg-muted/40 px-1.5 py-0.5 text-xs" title={s.code}>
                      {s.name}<span className="ml-1 text-muted-foreground">{s.sector}</span>
                      <span className={cn("ml-1 font-mono font-semibold", (s.pct ?? 0) > 0 ? "text-danger" : (s.pct ?? 0) < 0 ? "text-success" : "")}>{fmt(s.pct)}%</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border/50 text-left text-[11px] text-muted-foreground">
                    {["名称", "代码", "板位", "板块", "竞价%"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-1.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(auction.stocks ?? []).map((s) => (
                    <tr key={s.code} className="border-b border-border/30">
                      <td className="px-2 py-1.5">{s.name}</td>
                      <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{s.code}</td>
                      <td className="px-2 py-1.5">{s.tier}</td>
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">{s.sector}</td>
                      <td className={cn("px-2 py-1.5 font-mono font-semibold", (s.pct ?? 0) > 0 ? "text-danger" : (s.pct ?? 0) < 0 ? "text-success" : "")}>{fmt(s.pct)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(auction.notes ?? []).map((n, i) => <p key={i} className="mt-1.5 text-[11px] text-muted-foreground">{n}</p>)}
          </>
        )}
      </Section>

      {/* 六时点情绪路径 */}
      <Section title="今日情绪路径（六时点快照）" icon={<Activity className="h-4 w-4 text-muted-foreground" />} open={open === "epath"} onToggle={() => toggle("epath")}
        extra={<button onClick={capturePath} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><Zap className="h-3 w-3" /> 采集当前时点</button>}>
        {loading.epath ? <Loading /> : !epath ? <Empty msg="点击展开加载" /> : !epath.available ? <Err msg={epath.reason ?? epath.error ?? "不可用"} /> : (
          <>
            {epathMsg && <p className="mb-2 text-[11px] text-muted-foreground">{epathMsg}</p>}
            <div className="mb-2 text-xs text-muted-foreground">
              {epath.date} · 已采 {epath.captured?.length ?? 0}/{epath.timepoints?.length ?? 6} 时点
              {epath.missed?.length ? ` · 缺 ${epath.missed.join(",")}` : ""}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["时点", "采于", "涨停", "炸板", "跌停", "最高板", "连板", "封板率", "1进2", "昨涨停中位%"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(epath.points ?? []).map((p) => (
                    <tr key={p.timepoint} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-mono font-semibold">{p.timepoint}</td>
                      <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{p.captured_at ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono font-bold text-danger">{p.zt_count ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{p.zb_count ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{p.dt_count ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{p.max_boards ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{p.lianban_count ?? "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{pct(p.seal_rate)}</td>
                      <td className="px-2 py-1.5 font-mono">{pct(p.promotion_rate)}</td>
                      <td className={cn("px-2 py-1.5 font-mono font-semibold", (p.prev_median ?? 0) > 0 ? "text-danger" : (p.prev_median ?? 0) < 0 ? "text-success" : "")}>{fmt(p.prev_median)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!(epath.points ?? []).length && <Empty msg="今日尚无快照（点右上「采集当前时点」，或等定时任务）" />}
            <p className="mt-2 text-[11px] text-muted-foreground">{epath.note}</p>
          </>
        )}
      </Section>

      {/* 今日情绪完整页 */}
      <Section title="今日情绪完整页（天梯 · 断层 · 封板质量 · 溢价 · 周期）" icon={<Layers className="h-4 w-4 text-muted-foreground" />} open={open === "today"} onToggle={() => toggle("today")}
        extra={<button onClick={() => reload("today")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.today ? <Loading /> : !todayEmo ? <Empty msg="点击展开加载" /> : !todayEmo.available ? <Err msg={todayEmo.reason ?? todayEmo.error ?? "不可用"} /> : (
          <>
            <div className="mb-3 grid grid-cols-4 gap-2">
              {[
                { k: "涨停", v: todayEmo.summary?.zt },
                { k: "炸板", v: todayEmo.summary?.zb },
                { k: "跌停", v: todayEmo.summary?.dt },
                { k: "最高板", v: todayEmo.summary?.max_boards },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{m.k}</p>
                  <p className="mt-0.5 font-mono text-sm font-bold">{m.v ?? "—"}</p>
                </div>
              ))}
            </div>
            <p className="mb-1.5 text-xs font-semibold text-muted-foreground">连板天梯{todayEmo.ladder_note ? `（${todayEmo.ladder_note}）` : ""}</p>
            <div className="mb-3 space-y-1">
              {(todayEmo.ladder ?? []).filter((t) => (t.stocks ?? []).length).slice(0, 8).map((t) => {
                const all = t.stocks ?? [];
                const shown = t.boards === 1 ? all.slice(0, 12) : all;
                return (
                  <div key={t.boards} className="flex items-start gap-2 text-sm">
                    <span className="w-12 shrink-0 font-mono font-bold text-danger">{t.boards}板<span className="ml-1 text-[10px] text-muted-foreground">×{t.count}</span></span>
                    <div className="flex flex-wrap gap-1.5">
                      {shown.map((s) => (
                        <span key={s.code} className="rounded bg-muted/40 px-1.5 py-0.5 text-xs" title={`${s.code}${s.seal_time ? ` 首封 ${s.seal_time}` : ""}`}>
                          {s.name}<span className="ml-1 text-muted-foreground">{s.sector}</span>
                        </span>
                      ))}
                      {shown.length < all.length && <span className="px-1 py-0.5 text-xs text-muted-foreground">…共 {all.length}</span>}
                    </div>
                  </div>
                );
              })}
              {!(todayEmo.ladder ?? []).length && <p className="text-xs text-muted-foreground">无天梯数据</p>}
            </div>
            <div className="grid gap-3 lg:grid-cols-3">
              <BlockCard title="梯队断层" b={todayEmo.ladder_gap} rows={[
                ["最高板", (x) => x.highest ?? "—"],
                ["板位结构", (x) => Object.entries(x.tiers ?? {}).map(([k, v]) => `${k}板×${v}`).join("  ") || "—"],
                ["断层", (x) => (x.gaps ?? []).length ? `${x.gaps.length} 处` : (x.continuous ? "无（连续）" : "—")],
                ["注", (x) => <span className="text-[11px] text-muted-foreground">{x.note ?? ""}</span>],
              ]} />
              <BlockCard title="封板质量" b={todayEmo.seal_quality} rows={[
                ["炸板率", (x) => pct(x.broken_rate)],
                ["从未炸板", (x) => `${x.never_broken}家 (${pct(x.never_broken_rate)})`],
                ["秒板/首封", (x) => `${x.opening_seconds}家`],
                ["尾盘封", (x) => `${x.late_seal}家`],
                ["回封", (x) => `${x.reopened}家 · 均炸${x.avg_broken_times}次`],
              ]} />
              <BlockCard title="连板溢价（昨日连板今日表现）" b={todayEmo.consec_premium} rows={[
                ["样本", (x) => `${x.sample}只 (覆盖${pct(x.coverage_rate)})`],
                ["中位", (x) => `${fmt(x.median)}%`],
                ["均值", (x) => `${fmt(x.avg)}%`],
                ["正收益", (x) => pct(x.positive_rate)],
              ]} />
              <BlockCard title="赚钱效应（昨日涨停今日表现）" b={todayEmo.money_effect} rows={[
                ["样本", (x) => `${x.sample}只 (覆盖${pct(x.coverage_rate)})`],
                ["中位", (x) => `${fmt(x.median)}%`],
                ["正收益", (x) => pct(x.positive_rate)],
                ["再涨停", (x) => pct(x.limit_up_again_rate)],
              ]} />
              <BlockCard title="情绪周期（近 10 日窗口）" b={todayEmo.cycle} rows={[
                ["低点", (x) => `${x.trough_date ?? "—"} (分${x.trough_score})`],
                ["第几天", (x) => `第${x.day_n}天`],
                ["当前分", (x) => `${x.current_score} · ${x.trend ?? ""}`],
                ["窗口分位", (x) => pct(x.pctile)],
              ]} />
            </div>
          </>
        )}
      </Section>

      {/* 盯盘异动 */}
      <Section title="盯盘异动（3 分钟 ±1.5% · 封板开板 · 自选池）" icon={<Radar className="h-4 w-4 text-muted-foreground" />} open={open === "movers"} onToggle={() => toggle("movers")}
        extra={<button onClick={() => reload("movers")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.movers ? <Loading /> : !movers ? <Empty msg="点击展开加载" /> : !movers.available ? <Err msg={movers.reason ?? movers.error ?? "不可用"} /> : (
          <>
            <div className="mb-2 text-xs text-muted-foreground">
              {movers.as_of} · 盯 {movers.n_codes} 只 · 阈值 ±{movers.threshold}%/{movers.minutes}分钟 · 每 60 秒自动刷新
              {movers.reason ? ` · ${movers.reason}` : ""}
              {movers.failed?.length ? ` · 无今日分时 ${movers.failed.length} 只` : ""}
            </div>
            {(movers.movers ?? []).length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["时间", "代码", "名称", "类型", "变动", "现价"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(movers.movers ?? []).map((e, i) => (
                      <tr key={`${e.code}-${e.kind}-${e.time}-${i}`} className="border-b border-border/30">
                        <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{e.time}</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{e.code}</td>
                        <td className="px-2 py-1.5">{e.name || "—"}</td>
                        <td className={cn("px-2 py-1.5 font-semibold", KIND_CLS[e.kind] ?? "text-muted-foreground")}>{KIND_LABEL[e.kind] ?? e.kind}</td>
                        <td className={cn("px-2 py-1.5 font-mono font-semibold", e.pct > 0 ? "text-danger" : "text-success")}>{e.pct > 0 ? "+" : ""}{e.pct}%</td>
                        <td className="px-2 py-1.5 font-mono">{e.price}{e.limit_price ? <span className="text-[11px] text-muted-foreground"> /板{e.limit_price}</span> : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty msg="暂无异动" />}
            <p className="mt-2 text-[11px] text-muted-foreground">{movers.note}</p>
          </>
        )}
      </Section>

      {/* 自选池与候选池 */}
      <Section title="自选池与候选池（持仓 · 观察 · 候选 + 每笔年化）" icon={<Inbox className="h-4 w-4 text-muted-foreground" />} open={open === "pool"} onToggle={() => toggle("pool")}
        extra={<button onClick={() => reload("pool")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.pool ? <Loading /> : !pool ? <Empty msg="点击展开加载" /> : !pool.available ? <Err msg={pool.reason ?? pool.error ?? "不可用"} /> : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "持仓", v: pool.counts?.holding ?? 0 },
                { k: "观察", v: pool.counts?.observation ?? 0 },
                { k: "候选", v: pool.counts?.candidate ?? 0 },
                { k: "已了结(胜/年化中位)", v: `${pool.history?.closed_n ?? 0}（${pool.history?.win_n ?? 0}胜 · ${pool.history?.median_xirr_pct != null ? `${pool.history.median_xirr_pct}%` : "—"}）` },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{m.k}</p>
                  <p className="mt-0.5 font-mono text-sm font-bold">{m.v}</p>
                </div>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["分类", "代码", "名称", "现价", "今日", "成本", "浮盈", "止损/止盈", "备注"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(pool.positions ?? []).map((p) => (
                    <tr key={p.code} className="border-b border-border/30">
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">{CAT_LABEL[p.category] ?? p.category}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{p.code}</td>
                      <td className="px-2 py-1.5">{p.name || "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{p.price ?? "—"}</td>
                      <td className={cn("px-2 py-1.5 font-mono", (p.pct ?? 0) > 0 ? "text-danger" : (p.pct ?? 0) < 0 ? "text-success" : "")}>{p.pct != null ? `${p.pct > 0 ? "+" : ""}${p.pct}%` : "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{p.cost_price ?? "—"}</td>
                      <td className={cn("px-2 py-1.5 font-mono", (p.pnl_pct ?? 0) > 0 ? "text-danger" : (p.pnl_pct ?? 0) < 0 ? "text-success" : "")}>{p.pnl_pct != null ? `${p.pnl_pct > 0 ? "+" : ""}${p.pnl_pct}%` : "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">{p.stop_loss ?? "—"} / {p.take_profit ?? "—"}</td>
                      <td className="px-2 py-1.5 text-xs max-w-[160px] truncate" title={p.note}>{p.note || "—"}</td>
                    </tr>
                  ))}
                  {!(pool.positions ?? []).length && <tr><td colSpan={9} className="px-2 py-3 text-center text-xs text-muted-foreground">池子为空</td></tr>}
                </tbody>
              </table>
            </div>
            {(pool.history?.per_lot ?? []).length ? (
              <div className="mt-3">
                <p className="mb-1.5 text-xs font-semibold text-muted-foreground">已了结（每笔年化 XIRR）</p>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-[11px] text-muted-foreground">
                      {["代码", "买入", "卖出", "持有", "收益%", "离场", "年化XIRR"].map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(pool.history?.per_lot ?? []).map((h, i) => (
                      <tr key={`${h.code}-${i}`} className="border-b border-border/30">
                        <td className="px-2 py-1.5 font-mono text-xs">{h.code}</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{h.buy_date}</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{h.sell_date}</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{h.hold_days ?? "—"}天</td>
                        <td className={cn("px-2 py-1.5 font-mono", (h.pnl_pct ?? 0) > 0 ? "text-danger" : "text-success")}>{h.pnl_pct}</td>
                        <td className="px-2 py-1.5 text-xs">{h.sell_reason || "—"}</td>
                        <td className={cn("px-2 py-1.5 font-mono font-semibold", (h.xirr ?? 0) > 0 ? "text-danger" : (h.xirr ?? 0) < 0 ? "text-success" : "text-muted-foreground")}>{h.xirr != null ? `${h.xirr}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <p className="mt-2 text-[11px] text-muted-foreground">
              行情 {pool.quotes_as_of || "未取到"} · {pool.history?.note}
            </p>
          </>
        )}
      </Section>

      {/* 个股研究台 */}
      <Section title="个股研究台（资讯 · 研报 · AI 深挖 · 多空辩论）" icon={<Newspaper className="h-4 w-4 text-muted-foreground" />} open={open === "desk"} onToggle={() => toggle("desk")}>
        <StockResearchDesk />
      </Section>

      {/* 事件日历 */}
      <Section title="事件日历（财报预约 · 限售解禁 · 自选池）" icon={<CalendarDays className="h-4 w-4 text-muted-foreground" />} open={open === "calendar"} onToggle={() => toggle("calendar")}
        extra={<button onClick={() => reload("calendar")} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted"><RefreshCw className="h-3 w-3" /> 刷新</button>}>
        {loading.calendar ? <Loading /> : !calendar ? <Empty msg="点击展开加载（含 akshare 全市场披露表，约 5-15 秒）" /> : !calendar.available ? <Err msg={calendar.reason ?? calendar.error ?? "不可用"} /> : (
          <>
            <div className="mb-2 text-xs text-muted-foreground">
              截至 {calendar.as_of} · 未来 {calendar.days} 天{calendar.cached ? " · 缓存(TTL 6h)" : ""}
              {calendar.failed?.length ? <span className="text-warning"> · 失败: {calendar.failed.join(",")}</span> : null}
            </div>
            <p className="mb-1.5 text-xs font-semibold text-muted-foreground">财报预约披露（报告期 {calendar.disclosure?.period || "—"}）</p>
            {(calendar.disclosure?.rows ?? []).length ? (
              <table className="w-full text-sm mb-3">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["预约日", "代码", "名称", "报告期"].map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(calendar.disclosure?.rows ?? []).map((r, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-mono font-semibold">{r.date}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.code}</td>
                      <td className="px-2 py-1.5">{r.name}</td>
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">{r.period}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="mb-3 text-xs text-muted-foreground">窗口内无未披露财报预约</p>}
            <p className="mb-1.5 text-xs font-semibold text-muted-foreground">限售解禁</p>
            {(calendar.unlock ?? []).length ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["解禁日", "代码", "名称", "解禁(亿股)", "市值(亿)", "占流通%", "类型", "股东数"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-1.5 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(calendar.unlock ?? []).map((r, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="px-2 py-1.5 font-mono font-semibold">{r.date}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.code}</td>
                      <td className="px-2 py-1.5">{r.name}</td>
                      <td className="px-2 py-1.5 font-mono">{r.shares_yi}</td>
                      <td className="px-2 py-1.5 font-mono">{r.mv_yi ?? "—"}</td>
                      <td className={cn("px-2 py-1.5 font-mono", (r.float_pct ?? 0) >= 5 ? "text-warning font-semibold" : "")}>{r.float_pct}</td>
                      <td className="px-2 py-1.5 text-xs">{r.kind}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.holders}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-xs text-muted-foreground">窗口内无解禁</p>}
            <p className="mt-2 text-[11px] text-muted-foreground">{calendar.note}</p>
          </>
        )}
      </Section>

      {/* 板块研究 */}
      <Section title="板块研究（热度 Top 题材 · LLM 产业解读）" icon={<BookOpen className="h-4 w-4 text-muted-foreground" />} open={open === "sector"} onToggle={() => toggle("sector")}
        extra={
          <button onClick={runSectorAi} disabled={secRunning} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted disabled:opacity-50">
            {secRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <BookOpen className="h-3 w-3" />} {secRunning ? "生成中" : "生成研究"}
          </button>
        }>
        {loading.sector ? <Loading /> : null}
        {secRunning && secOutput && <pre className="mb-2 max-h-32 overflow-auto rounded bg-muted/20 p-2 text-[11px] whitespace-pre-wrap">{secOutput}</pre>}
        {sector?.available && sector.markdown ? (
          <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
            <p className="mb-2 text-xs text-muted-foreground">生成于 {sector.generated_at}</p>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{sector.markdown}</ReactMarkdown>
          </div>
        ) : !secRunning && sector ? (
          <Empty msg={sector.reason ?? "尚未生成，点右上「生成研究」（约 2-3 分钟）"} />
        ) : null}
      </Section>

      {/* AI 周报 */}
      <Section title="AI 周报（情绪走势 · 题材轮动 · 验证回看）" icon={<FileText className="h-4 w-4 text-muted-foreground" />} open={open === "weekly"} onToggle={() => toggle("weekly")}
        extra={
          <button onClick={runWeeklyAi} disabled={wkRunning} className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded hover:bg-muted disabled:opacity-50">
            {wkRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileText className="h-3 w-3" />} {wkRunning ? "生成中" : "生成周报"}
          </button>
        }>
        {loading.weekly ? <Loading /> : null}
        {wkRunning && wkOutput && <pre className="mb-2 max-h-32 overflow-auto rounded bg-muted/20 p-2 text-[11px] whitespace-pre-wrap">{wkOutput}</pre>}
        {weeklyAi?.available && weeklyAi.markdown ? (
          <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
            <p className="mb-2 text-xs text-muted-foreground">窗口 {weeklyAi.dates?.join(" ~ ")}</p>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{weeklyAi.markdown}</ReactMarkdown>
          </div>
        ) : !wkRunning && weeklyAi ? (
          <Empty msg={weeklyAi.reason ?? "尚未生成，点右上「生成周报」（约 1-3 分钟）"} />
        ) : null}
      </Section>
    </div>
  );
}

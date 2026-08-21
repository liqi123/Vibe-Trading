import { useState, useEffect, useCallback } from "react";
import { Sparkles, Loader2, AlertCircle, RefreshCw, Gauge, ArrowDownUp, TrendingUp, TrendingDown, Flame, BarChart3, Globe, LineChart, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

// A股红涨绿跌（含全球市场，与东财等国内平台一致，有意约定勿改）
const pctColor = (p: number) => (p > 0 ? "text-danger" : p < 0 ? "text-success" : "text-muted-foreground");
const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`);
const localDate = (d?: Date) => {
  const x = d || new Date();
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};

interface IndexQuote {
  name: string; price: number; change_pct: number;
}
interface GlobalIndex {
  key: string; name: string; region: string;
  price: number | null; change_pct: number | null;
}
interface MarketSentiment {
  up: number; down: number; flat: number;
  zt: number; zt_real: number; dt: number; dt_real: number;
  breadth: string; speculation: string; date: string;
}
interface SectorFlow {
  name: string; pct: number; net: number;
  inflow: number | null; outflow: number | null; firms: number;
}
interface LianbanStock {
  code: string; name: string; boards: number;
  price: number; pct: number; amount: number | null; float_cap: number | null; industry: string;
}
interface ShortTermEmotion {
  date: string;
  zt_count: number; dt_count: number; zb_count: number;
  max_boards: number; lianban_count: number;
  lianban_stocks: LianbanStock[];
  seal_rate: number | null; break_rate: number | null; promotion_rate: number | null;
}
interface TurnoverStock {
  code: string; name: string;
  price: number | null; pct: number | null;
  amount: number | null; mcap: number | null; industry: string;
}
interface MarketPulse {
  sentiment: MarketSentiment | null;
  sectors: SectorFlow[];
  updated: string;
}
interface TurnoverTop { stocks: TurnoverStock[]; updated: string }

export function MarketReview() {
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [idxErr, setIdxErr] = useState(false);
  const [review, setReview] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewErr, setReviewErr] = useState<string | null>(null);
  const [pulse, setPulse] = useState<MarketPulse | null>(null);
  const [emotion, setEmotion] = useState<ShortTermEmotion | null>(null);
  const [turnover, setTurnover] = useState<TurnoverTop | null>(null);
  const [globalIdx, setGlobalIdx] = useState<GlobalIndex[]>([]);

  const [ovDone, setOvDone] = useState(false);
  const [emoDone, setEmoDone] = useState(false);
  const [toDone, setToDone] = useState(false);

  // 复盘报告（原 /daily-review 功能）：运行本地 review_v5 脚本生成当日报告
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const loadAll = () => {
    api.tools.get<IndexQuote[]>("/market/indices").then(setIndices).catch(() => setIdxErr(true));
    api.tools.get<GlobalIndex[]>("/market/global-indices").then(setGlobalIdx).catch(() => {});
    api.tools.get<MarketPulse>("/market/pulse").then(setPulse).catch(() => {}).finally(() => setOvDone(true));
    api.tools.get<ShortTermEmotion>("/market/emotion").then(setEmotion).catch(() => {}).finally(() => setEmoDone(true));
    api.tools.get<TurnoverTop>("/market/turnover-top").then(setTurnover).catch(() => {}).finally(() => setToDone(true));
  };

  useEffect(() => { loadAll(); }, []);

  // 已有复盘报告（当天，优先后端、回退 localStorage）
  useEffect(() => {
    const today = localDate();
    const ctrl = new AbortController();
    api.tools.get<any>(`/review-report?date=${today}`, ctrl.signal)
      .then((d) => { if (d?.content) setReport(d.content); })
      .catch(() => {
        if (!ctrl.signal.aborted) {
          const cached = localStorage.getItem(`review_report_${today}`);
          if (cached) setReport(cached);
        }
      });
    return () => ctrl.abort();
  }, []);

  const loadExistingReport = async () => {
    try {
      const today = localDate();
      const d = await api.tools.get<any>(`/review-report?date=${today}`);
      if (d?.content) {
        setReport(d.content);
        localStorage.setItem(`review_report_${today}`, d.content);
        return;
      }
      const cached = localStorage.getItem(`review_report_${today}`);
      if (cached) { setReport(cached); return; }
      setReport("生成失败，且无已有报告可展示");
    } catch { /* ignore */ }
  };

  const generateReport = useCallback(async () => {
    setGenerating(true);
    setReport(null);
    try {
      const { task_id } = await api.tools.post<any>("/run-script", { script: "review_v5", args: localDate() });

      let output = "";
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const data = await api.tools.get<any>(`/run-script/${task_id}`);
        output = data.output || "";
        if (output.includes("执行完成") || output.includes("错误") || output.includes("超时")) break;
      }

      const body = output.replace(/^\[.*?\] 执行完成 \(exit=\d+\)\s*\n\n?/, "").trim();
      const result = body || output;

      if (result && !result.includes("Traceback")) {
        setReport(result);
        localStorage.setItem(`review_report_${localDate()}`, result);
      } else {
        await loadExistingReport();
      }
    } catch (e) {
      await loadExistingReport();
    } finally {
      setGenerating(false);
    }
  }, []);

  const pending = (done: boolean) => (
    <p className="py-4 text-center text-sm text-muted-foreground/60">
      {done ? "暂无数据：可能是非交易时段或数据源暂时不可用，可点「大盘指数」旁的刷新重试" : "加载中…"}
    </p>
  );

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  // 组装喂给 AI 的完整客观语料（指数/全球/情绪/短线情绪/板块资金/成交额榜）
  const buildSummary = () => {
    const lines: string[] = [];
    if (indices.length) {
      lines.push("【A股指数】" + indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；"));
    }
    if (globalIdx.length) {
      lines.push("【全球市场】" + globalIdx.map((g) => `${g.name} ${g.price ?? "—"}（${g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}）`).join("；"));
    }
    if (sentiment) {
      lines.push(`【市场情绪】上涨${sentiment.up} 下跌${sentiment.down} 平盘${sentiment.flat}；涨停${sentiment.zt} 真实涨停${sentiment.zt_real} 跌停${sentiment.dt} 真实跌停${sentiment.dt_real}；大盘宽度：${sentiment.breadth}；题材投机：${sentiment.speculation}`);
    }
    if (emotion && emotion.zt_count !== undefined) {
      const rates = [
        emotion.seal_rate != null ? `封板率${(emotion.seal_rate * 100).toFixed(1)}%` : "",
        emotion.break_rate != null ? `炸板率${(emotion.break_rate * 100).toFixed(1)}%` : "",
        emotion.promotion_rate != null ? `晋级率${(emotion.promotion_rate * 100).toFixed(1)}%` : "",
      ].filter(Boolean).join(" ");
      const stocks = emotion.lianban_stocks.length
        ? "；连板股：" + emotion.lianban_stocks.slice(0, 10).map((s) => `${s.name}(${s.boards}板,现价${s.price},${s.pct > 0 ? "+" : ""}${s.pct}%,${s.industry})`).join("、")
        : "";
      lines.push(`【短线情绪】涨停${emotion.zt_count} 跌停${emotion.dt_count} 炸板${emotion.zb_count} 最高连板${emotion.max_boards}板 连板股${emotion.lianban_count}家${rates ? " " + rates : ""}${stocks}`);
    }
    if (sectors.length) {
      lines.push("【板块资金流】" + sectors.slice(0, 15).map((s) => `${s.name} ${s.pct > 0 ? "+" : ""}${s.pct}% 净流入${s.net == null ? "—" : `${s.net > 0 ? "+" : ""}${s.net}亿`}`).join("；"));
    }
    if (turnover?.stocks.length) {
      lines.push("【成交额榜】" + turnover.stocks.slice(0, 10).map((s) => `${s.name} ${s.price ?? "—"}（${s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}）成交额${yi(s.amount)}`).join("；"));
    }
    return lines.length ? lines.join("\n") : "（大盘数据未取到）";
  };

  const runReview = async () => {
    setReviewErr(null);
    setReviewLoading(true);
    setReview("");
    try {
      const res = await api.tools.post<{ report?: string; error?: string }>("/ai/review", {
        summary: `以下是今天 A 股大盘的客观数据：\n${buildSummary()}`,
      });
      if (res.error) setReviewErr(res.error);
      else setReview(res.report || "");
    } catch (e) {
      setReviewErr(e instanceof Error ? e.message : "复盘失败");
    } finally {
      setReviewLoading(false);
    }
  };

  const sentiment = pulse?.sentiment;
  const sectors = pulse?.sectors || [];
  const sentCells = sentiment ? [
    { k: "上涨家数", v: sentiment.up, up: true },
    { k: "下跌家数", v: sentiment.down, up: false },
    { k: "平盘", v: sentiment.flat, up: null },
    { k: "涨停", v: sentiment.zt, up: true },
    { k: "真实涨停", v: sentiment.zt_real, up: true },
    { k: "跌停", v: sentiment.dt, up: false },
    { k: "真实跌停", v: sentiment.dt_real, up: false },
  ] : [];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <LineChart className="h-6 w-6" />
            每日复盘
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{today} · 大盘 / 情绪 / 板块资金一屏看全，交给 AI 做复盘</p>
        </div>
      </div>

      {/* 1. 大盘指数（实时） */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">大盘指数</h3>
        <button onClick={loadAll} className="text-muted-foreground hover:text-primary" title="刷新">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {indices.length === 0
          ? [1, 2, 3, 4].map((i) => (
              <div key={i} className="border rounded-lg p-3 bg-card">
                <p className="text-xs text-muted-foreground">{idxErr ? "行情未接通" : "加载中…"}</p>
                <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
              </div>
            ))
          : indices.map((i) => (
              <div key={i.name} className="border rounded-lg p-3 bg-card">
                <p className="truncate text-xs text-muted-foreground">{i.name}</p>
                <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(i.change_pct))}>{i.price}</p>
                <p className={cn("text-xs", pctColor(i.change_pct))}>{i.change_pct > 0 ? "+" : ""}{i.change_pct}%</p>
              </div>
            ))}
      </div>

      {/* 1b. 全球市场（隔夜外围脸色） */}
      {globalIdx.length > 0 && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 全球市场</h3>
            <span className="text-[11px] text-muted-foreground/50">隔夜外围 · A 股常看美股 / 港股脸色</span>
          </div>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {globalIdx.map((g) => (
              <div key={g.key} className="border rounded-lg p-3 bg-card">
                <p className="truncate text-xs text-muted-foreground">{g.name} <span className="text-muted-foreground/40">{g.region}</span></p>
                <p className={cn("mt-1 font-mono text-lg font-bold", g.change_pct == null ? "text-foreground" : pctColor(g.change_pct))}>{g.price ?? "—"}</p>
                <p className={cn("text-xs", g.change_pct == null ? "text-muted-foreground" : pctColor(g.change_pct))}>
                  {g.change_pct == null ? "—" : `${g.change_pct > 0 ? "+" : ""}${g.change_pct}%`}
                </p>
              </div>
            ))}
          </div>
        </>
      )}

      {/* 2. AI 当日复盘 */}
      <div className="border rounded-lg p-4 bg-card">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 font-semibold"><Sparkles className="h-4 w-4 text-primary" /> AI 当日复盘</h3>
          <button onClick={runReview} disabled={reviewLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50">
            {reviewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {review ? "重新复盘" : "让 AI 复盘今天"}
          </button>
        </div>
        {reviewErr && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {reviewErr}
          </div>
        )}
        {review ? (
          <div className="prose prose-sm prose-invert mt-4 max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{review}</ReactMarkdown></div>
        ) : !reviewErr && !reviewLoading ? (
          <p className="mt-3 text-sm text-muted-foreground">点上方按钮，系统把当天客观数据打包给 AI，由它生成复盘。<b className="text-foreground">分析是它给的，我们只负责喂数据。</b></p>
        ) : null}
      </div>

      {/* 2b. 复盘报告（本地数据完整版） */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <FileText className="h-4 w-4" />
            复盘报告
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={generateReport}
              disabled={generating}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${generating ? "animate-spin" : ""}`} />
              {generating ? "生成中..." : (report ? "生成新报告" : "生成")}
            </button>
          </div>
        </div>
        {report ? (
          <div className="relative">
            <button
              onClick={() => { navigator.clipboard.writeText(report); }}
              className="absolute top-2 right-2 z-10 text-xs px-2 py-1 border rounded hover:bg-muted"
            >
              复制
            </button>
            <div className="p-4 text-sm overflow-auto max-h-[600px] leading-relaxed prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{report}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            <FileText className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">点击上方「生成」按钮生成今日复盘报告（含持仓、交易统计，基于本地数据库）</p>
          </div>
        )}
      </div>

      {/* 3. 市场情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Gauge className="h-4 w-4" /> 市场情绪</h3>
        {sentiment?.date && <span className="text-[11px] text-muted-foreground/50">{sentiment.date}</span>}
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {!sentiment ? (
          pending(ovDone)
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { k: "大盘宽度", v: sentiment.breadth, hint: "冰点 / 偏弱 / 中性 / 偏强 / 普涨" },
                { k: "题材投机", v: sentiment.speculation, hint: "冰点 / 普通 / 活跃 / 亢奋" },
              ].map((m) => (
                <div key={m.k} className="rounded-lg bg-muted/25 p-4">
                  <p className="text-xs text-muted-foreground">{m.k}</p>
                  <p className="mt-1 text-2xl font-bold text-primary">{m.v}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground/60">{m.hint}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              {sentCells.map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2 text-center">
                  <p className="truncate text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.up === null ? "text-foreground" : c.up ? "text-danger" : "text-success")}>{c.v}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* 4. 短线情绪（连板梯队 / 打板情绪，东财涨停四池） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 短线情绪</h3>
        <span className="text-[11px] text-muted-foreground/50">连板股 · 打板情绪 · 客观公开榜单</span>
        {emotion?.date && <span className="ml-auto text-[11px] text-muted-foreground/50">{emotion.date}</span>}
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {!emotion || emotion.zt_count === undefined ? (
          pending(emoDone)
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "涨停", v: `${emotion.zt_count}`, cls: "text-danger" },
                { k: "跌停", v: `${emotion.dt_count}`, cls: "text-success" },
                { k: "最高连板", v: `${emotion.max_boards} 板`, cls: "text-primary" },
                { k: "连板（2板+）", v: `${emotion.lianban_count} 家`, cls: "text-primary" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                { k: "封板率", v: emotion.seal_rate, hint: "封住 / 尝试涨停", strong: true },
                { k: "炸板率", v: emotion.break_rate, hint: "炸板 / 尝试涨停", strong: false },
                { k: "晋级率", v: emotion.promotion_rate, hint: "昨涨停今又停", strong: true },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
                    {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground/50">{c.hint}</p>
                </div>
              ))}
            </div>
            <div className="mt-3">
              <p className="mb-1.5 text-[11px] text-muted-foreground">连板股（2 板以上连续涨停）· 客观公开榜单，非推荐 / 非预测</p>
              {emotion.lianban_stocks.length === 0 ? (
                <p className="text-xs text-muted-foreground/50">今日无 2 板以上个股</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                        {["名称", "连板", "现价", "涨停%", "成交额", "流通市值", "概念"].map((h) => (
                          <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {emotion.lianban_stocks.map((s) => (
                        <tr key={s.code} className="border-b border-border/30">
                          <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                          <td className="px-2 py-2 font-mono">{s.price}</td>
                          <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
                          <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 5. 全市场成交额 TOP20 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><BarChart3 className="h-4 w-4" /> 全市场成交额 TOP20</h3>
        <span className="text-[11px] text-muted-foreground/50">客观公开榜单，非推荐 / 非预测</span>
        {turnover?.updated && <span className="ml-auto text-[11px] text-muted-foreground/50">{turnover.updated}</span>}
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {!turnover || turnover.stocks.length === 0 ? (
          pending(toDone)
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["#", "名称", "现价", "涨跌%", "成交额", "总市值", "行业"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {turnover.stocks.map((s, i) => (
                  <tr key={s.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                    <td className="px-2 py-2 font-mono">{s.price ?? "—"}</td>
                    <td className={cn("px-2 py-2 font-mono", s.pct == null ? "text-muted-foreground" : pctColor(s.pct))}>
                      {s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.mcap)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 6. 板块资金趋势榜（行业） */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><TrendingUp className="h-4 w-4" /> 板块资金趋势榜</h3>
        <span className="text-[11px] text-muted-foreground/50">行业 · 按今日主力净流入排序</span>
      </div>
      <div className="border rounded-lg p-4 bg-card">
        {sectors.length === 0 ? (
          pending(ovDone)
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["行业", "涨跌%", "今日净流入", "流入", "流出", "家数"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sectors.slice(0, 15).map((s) => (
                  <tr key={s.name} className="border-b border-border/30">
                    <td className="px-2 py-2 font-medium">{s.name}</td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.net))}>{s.net == null ? "—" : `${s.net > 0 ? "+" : ""}${fmt(s.net)} 亿`}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.inflow == null ? "—" : fmt(s.inflow)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.outflow == null ? "—" : fmt(s.outflow)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 7. 资金轮动 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><ArrowDownUp className="h-4 w-4" /> 资金轮动</h3>
        <span className="text-[11px] text-muted-foreground/50">板块级净流入 / 流出</span>
      </div>
      <div className="mb-2 grid gap-4 md:grid-cols-2">
        {[
          { title: "流入 Top", icon: TrendingUp, color: "text-danger", rows: sectors.slice(0, 6) },
          { title: "流出 Top", icon: TrendingDown, color: "text-success", rows: [...sectors].slice(-6).reverse() },
        ].map((col) => (
          <div key={col.title} className="border rounded-lg p-4 bg-card">
            <h4 className={cn("mb-3 flex items-center gap-1.5 text-sm font-semibold", col.color)}><col.icon className="h-4 w-4" /> {col.title}</h4>
            {col.rows.length === 0 ? (
              pending(ovDone)
            ) : (
              <div className="space-y-1.5">
                {col.rows.map((s, i) => (
                  <div key={s.name} className="flex items-center gap-3 border-b border-border/30 pb-1.5 text-sm last:border-0">
                    <span className="w-5 text-xs text-muted-foreground/50">{i + 1}</span>
                    <span className="flex-1 truncate">{s.name}</span>
                    <span className={cn("font-mono text-xs", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                    <span className={cn("w-20 text-right font-mono text-xs", pctColor(s.net))}>{s.net == null ? "—" : `${s.net > 0 ? "+" : ""}${fmt(s.net)} 亿`}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="text-xs text-muted-foreground/60">以上均为客观公开数据（腾讯 / 东方财富），非推荐 / 非预测 / 不构成投资建议。</p>
    </div>
  );
}

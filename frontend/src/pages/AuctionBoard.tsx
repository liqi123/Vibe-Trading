import { useEffect, useState, useCallback, Fragment, useRef } from "react";
import { toast } from "sonner";
import { RefreshCw, Zap, TrendingUp, TrendingDown, BarChart3, Calendar, Eye, Plus, Trash2, Sparkles, Camera, Search, Bot, ArrowUpRight, ChevronDown, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { useLLMWebAsk } from "@/hooks/useLLMWebAsk";
import { SENTIMENT_PROMPT, LLM_OPTIONS } from "@/lib/auctionAi";

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

interface GapUpStock {
  code: string; name: string; auction_price: number; prev_close: number;
  chg_pct: number; auction_vol: number; auction_amount_wan: number;
  prev_auction_vol: number; vol_ratio: number | null;
  prev_high: number | null; gap_break_prev_high: boolean;
  top_industry?: string | null; top_industry_chg?: number | null;
}

function volClass(v: number) {
  if (v > 0) return "text-red-600";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function auctionChgCell(v: number | null) {
  if (v == null) return <td className="px-3 py-2 text-right text-muted-foreground">-</td>;
  const cls = v >= 0 ? "text-red-600" : "text-green-600";
  return <td className={`px-3 py-2 text-right font-medium ${cls}`}>{v >= 0 ? "+" : ""}{v.toFixed(2)}%</td>;
}

export function AuctionBoard() {
  const { askOne, askMany } = useLLMWebAsk();
  const [dates, setDates] = useState<DateInfo[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [collecting, setCollecting] = useState(false);
  const [snapshotting, setSnapshotting] = useState(false);
  const [tab, setTab] = useState<"limitup" | "compare" | "expectation" | "concept" | "ai" | "gapup">("limitup");
  const [limitUpData, setLimitUpData] = useState<{
    prev_limitup: any[];
    today_limitup: any[];
    both_limitup: any[];
    date1: string;
    date2: string;
    prev_count: number;
    today_count: number;
    both_count: number;
  } | null>(null);
  const [limitUpLoading, setLimitUpLoading] = useState(false);
  const [limitUpSubTab, setLimitUpSubTab] = useState<"both" | "yesterday" | "today">("both");
  const [compareData, setCompareData] = useState<{ date1: string; date2: string; gainers: CompareStock[]; losers: CompareStock[]; increase: number; decrease: number; total: number } | null>(null);
  const [expectStocks, setExpectStocks] = useState<ExpectStock[]>([]);
  const [expectItems, setExpectItems] = useState<ExpectAuctionItem[]>([]);
  const [expectLoading, setExpectLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [conceptLoading, setConceptLoading] = useState(false);
  const [sectorData, setSectorData] = useState<any[]>([]);
  const [expandedSector, setExpandedSector] = useState<string | null>(null);
  const [analysisSource, setAnalysisSource] = useState<"ths_industry" | "ths_concept">("ths_industry");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [searchMeta, setSearchMeta] = useState<any>(null);
  const [searching, setSearching] = useState(false);
  const [aiReport, setAiReport] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState("");
  const [showLlmMenu, setShowLlmMenu] = useState(false);
  const [pastedAnswer, setPastedAnswer] = useState("");
  const [askTarget, setAskTarget] = useState("");
  const [askLogs, setAskLogs] = useState<string[]>([]);
  const [webAnswers, setWebAnswers] = useState<{ target: string; label: string; answer: string }[]>([]);
  const [sendingAll, setSendingAll] = useState(false);
  const [auctionPreview, setAuctionPreview] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedStage, setSelectedStage] = useState<string>("auto");
  const [useFile, setUseFile] = useState<boolean>(false);
  const logBoxRef = useRef<HTMLDivElement | null>(null);
  const previewReqRef = useRef(0);
  const previewCacheRef = useRef<Record<string, { date: string; text: string }>>({});

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [askLogs]);

  const handleLlmLogin = async (key: string, label: string) => {
    setShowLlmMenu(false);
    setAskTarget(key);
    toast.info(`正在打开 ${label} 登录窗口，请在浏览器中完成登录后关闭该窗口`);
    try {
      const res = await api.tools.post<any>("/llm-web/login", { target: key });
      if (res.ok) {
        toast.success(`${label} 登录态已保存`);
      } else {
        throw new Error(res.detail || "登录保存失败");
      }
    } catch (e: any) {
      toast.error(`${label} 登录失败: ${e?.message || e}`);
    } finally {
      setAskTarget("");
    }
  };

  const fetchAuctionStage = async (stage?: string): Promise<string> => {
    try {
      const q = stage && stage !== "auto" ? `?stage=${stage}` : "";
      const info = await api.tools.get<any>(`/llm-web/auction-prompt${q}`);
      return info?.stage ?? "";
    } catch {
      return "";
    }
  };

  const fetchAuctionPreview = useCallback(async (stage?: string, force = false) => {
    // 自动/未选：留空，等用户手动选择阶段后再填充（不自动拉取，避免覆盖手动选择）
    if (!stage || stage === "auto") {
      setAuctionPreview("");
      return;
    }
    // 复用缓存时校验日期一致（本地信号/附件都是按日期算的），force 时忽略缓存重新拉
    const cached = previewCacheRef.current[stage];
    if (cached && cached.date === selectedDate && !force) {
      setAuctionPreview(cached.text);
      return;
    }
    setPreviewLoading(true);
    const reqId = ++previewReqRef.current;
    try {
      const dateQ = selectedDate ? `&date=${encodeURIComponent(selectedDate)}` : "";
      const info = await api.tools.get<any>(`/llm-web/auction-prompt?stage=${stage}${dateQ}`);
      // 仅采纳最新一次请求的结果
      if (reqId === previewReqRef.current && info?.prompt) {
        previewCacheRef.current[stage] = { date: selectedDate, text: info.prompt };
        setAuctionPreview(info.prompt);
      }
    } catch {
      /* ignore */
    } finally {
      if (reqId === previewReqRef.current) setPreviewLoading(false);
    }
  }, [selectedDate]);

  // 挂载时静默预取 ①~④（仅暖缓存，不填充/发送），手动点选即可秒出
  useEffect(() => {
    ["0", "1", "2", "3"].forEach((s) => {
      api.tools.get<any>(`/llm-web/auction-prompt?stage=${s}`)
        .then((info) => { if (info?.prompt) previewCacheRef.current[s] = { date: "", text: info.prompt }; })
        .catch(() => {});
    });
  }, []);

  useEffect(() => {
    fetchAuctionPreview(selectedStage);
  }, [selectedStage, fetchAuctionPreview]);

  const handleSendToLlm = async (key: string, label: string, url: string) => {
    setShowLlmMenu(false);
    if (selectedStage === "auto") {
      toast.warning("请先在阶段下拉中选择具体阶段（①~④）后再发送");
      return;
    }
    setAskTarget(key);
    const stage = await fetchAuctionStage(selectedStage);
    setAskLogs([`[${new Date().toLocaleTimeString()}] 提交任务到 ${label}${stage ? `（${stage}）` : ""}...`]);
    fetchAuctionPreview(selectedStage);
    try {
      const r = await askOne(
        {
          target: key,
          use_template: true,
          use_file: useFile,
          timeout_s: 120,
          stage: selectedStage !== "auto" ? Number(selectedStage) : undefined,
          date: selectedDate,
        },
        { pollMs: 1500, onLogs: (_t, logs) => setAskLogs(logs) },
      );
      setPastedAnswer(r.answer);
      toast.success(`${label} 回答已获取（${r.elapsed_s ?? "?"}s）`);
    } catch (e: any) {
      const msg = e?.message || String(e);
      setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ✗ ${msg}`]);
      // 兜底：复制「带本地数据的预览」并打开网页手动粘贴（不再用无数据的旧 SENTIMENT_PROMPT）
      toast.warning(`自动获取失败，已复制含本地数据的 prompt 并打开网页。可在下方日志查看原因`);
      try {
        await navigator.clipboard.writeText(
          auctionPreview || previewCacheRef.current[selectedStage]?.text || SENTIMENT_PROMPT,
        );
      } catch { /* ignore */ }
      window.open(url, "_blank");
    } finally {
      setAskTarget("");
    }
  };
  const handleSendAll = async () => {
    setShowLlmMenu(false);
    if (selectedStage === "auto") {
      toast.warning("请先在阶段下拉中选择具体阶段（①~④）后再一键发送");
      return;
    }
    const targets = LLM_OPTIONS;
    setSendingAll(true);
    setAskTarget("all");
    setWebAnswers([]);
    const stage = await fetchAuctionStage(selectedStage);
    setAskLogs([`[${new Date().toLocaleTimeString()}] 开始一键发送 ${targets.map((t) => t.label).join(" + ")}${stage ? `（${stage}）` : ""}...`]);
    fetchAuctionPreview(selectedStage);
    await askMany(
      targets.map((opt) => ({
        target: opt.key,
        label: opt.label,
        use_template: true,
        use_file: useFile,
        timeout_s: 120,
        stage: selectedStage !== "auto" ? Number(selectedStage) : undefined,
        date: selectedDate,
      })),
      {
        pollMs: 1500,
        onDone: (r) => {
          const label = targets.find((o) => o.key === r.target)?.label ?? r.target;
          if (r.error) {
            setWebAnswers((prev) => [...prev, { target: r.target, label, answer: `✗ ${label} 失败: ${r.error}` }]);
            setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ✗ ${label}: ${r.error}`]);
            toast.warning(`${label} 自动获取失败`);
          } else {
            setWebAnswers((prev) => [...prev, { target: r.target, label, answer: r.answer }]);
            setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ✓ ${label} 完成（${r.answer.length} 字）`]);
            toast.success(`${label} 回答已获取`);
          }
        },
      },
    );
    setAskLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 全部完成`]);
    setSendingAll(false);
    setAskTarget("");
  };

  const [gapUpData, setGapUpData] = useState<{ date: string; stocks: GapUpStock[] } | null>(null);
  const [gapUpLoading, setGapUpLoading] = useState(false);

  const fetchDates = async (selectLatest = false) => {
    try {
      const data = await api.tools.get<any>("/auction/dates");
      setDates(data.dates || []);
      if (data.dates?.length > 0 && (selectLatest || !selectedDate)) {
        setSelectedDate(data.dates[0].date);
      }
    } catch (e) { /* ignore */ }
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

  const fetchLimitUp = async () => {
    if (dates.length < 2) return;
    const d1 = selectedDate || dates[0].date;
    const d2 = dates.find(d => d.date !== d1)?.date || dates[1]?.date;
    if (!d2) return;
    setLimitUpLoading(true);
    try {
      const data = await api.tools.get<any>(`/auction/limit-up-compare?date1=${encodeURIComponent(d1)}&date2=${encodeURIComponent(d2)}`);
      setLimitUpData(data);
      if (data.both_limitup?.length > 0) setLimitUpSubTab("both");
    } catch (e) { /* ignore */ }
    finally { setLimitUpLoading(false); }
  };

  const handleSearch = useCallback(async () => {
    const kw = searchKeyword.trim();
    if (!kw || dates.length < 2) return;
    const d1 = selectedDate || dates[0].date;
    const d2 = dates.find(d => d.date !== d1)?.date || dates[1]?.date;
    if (!d2) return;
    setSearching(true);
    try {
      const data = await api.tools.get<any>(`/auction/search?keyword=${encodeURIComponent(kw)}&date1=${encodeURIComponent(d1)}&date2=${encodeURIComponent(d2)}&top=30`);
      setSearchResults(data.results || []);
      setSearchMeta(data);
    } catch (e) { /* ignore */ }
    finally { setSearching(false); }
  }, [searchKeyword, selectedDate, dates]);

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

  const handleSnapshot = async () => {
    setSnapshotting(true);
    try {
      const data = await api.tools.post<any>("/auction/snapshot");
      if (data.ok) {
        toast.success(data.message || "竞价快照定时任务已注册");
      } else {
        toast.error(data.error || "注册失败");
      }
    } catch (e) { toast.error("请求失败"); }
    finally { setSnapshotting(false); }
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

  const fetchConceptAnalysis = async (d?: string, src?: "ths_industry" | "ths_concept") => {
    setConceptLoading(true);
    try {
      const date = d || selectedDate || dates[0]?.date;
      if (!date) { toast.warning("请先选择日期"); return; }
      const s = src || analysisSource;
      // 最强行业 / 最强概念 共用 sector-strength 端点，source 区分口径
      const data = await api.tools.get<any>(
        `/auction/sector-strength?date=${encodeURIComponent(date)}&top_sectors=15&top_stocks=5&source=${s}`
      );
      if (data.error) { toast.error(`分析失败: ${data.error}`); return; }
      setSectorData(data.sectors || []);
      if (!data.sectors?.length) toast.info("该日期无数据");
    } catch (e: any) { toast.error(`请求失败: ${e.message || e}`); }
    finally { setConceptLoading(false); }
  };

  const fetchAiAnalysis = async () => {
    const d = selectedDate || dates[0]?.date;
    if (!d) { toast.warning("请先选择日期"); return; }
    setAiLoading(true);
    setAiReport("");
    setAiError("");
    try {
      const res = await api.tools.post<any>("/auction/ai-analysis", {
        date: d,
        concept_source: analysisSource === "ths_industry" ? "industry" : "concept",
        web_answers: webAnswers
          .filter((w) => w.answer && w.answer.trim())
          .map((w) => ({ target: w.target, label: w.label, answer: w.answer })),
      });
      if (res.error) {
        setAiError(res.error);
      } else {
        setAiReport(res.report || "");
      }
    } catch (e: any) {
      setAiError(e.message || String(e));
    } finally {
      setAiLoading(false);
    }
  };

  const fetchGapUp = async () => {
    if (!selectedDate) return;
    setGapUpLoading(true);
    try {
      const data = await api.tools.get<any>(`/auction/gap-up?date=${encodeURIComponent(selectedDate)}&min_chg=3&max_chg=9&min_vol_ratio=1&limit=100`);
      setGapUpData(data);
    } catch (e) { /* ignore */ }
    finally { setGapUpLoading(false); }
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

  const SectorStrengthView = ({
    source, sectors, loading, expanded, setExpanded,
  }: {
    source: "ths_industry" | "ths_concept";
    sectors: any[];
    loading: boolean;
    expanded: string | null;
    setExpanded: (s: string | null) => void;
  }) => {
    const groupLabel = source === "ths_concept" ? "概念" : "行业";
    const groupFull = source === "ths_concept" ? "概念（同花顺概念）" : "行业（同花顺行业）";
    if (loading) return <div className="p-8 text-center text-muted-foreground">加载中...</div>;
    if (!sectors || sectors.length === 0)
      return <div className="p-8 text-center text-muted-foreground">暂无数据（该日期无竞价或映射缺失）</div>;
    return (
      <div className="space-y-4">
        <div className="border rounded-lg bg-card p-3 text-xs text-muted-foreground leading-relaxed">
          按同花顺{groupLabel}分组。{groupLabel}强度分 = 均价涨幅45% + 上涨占比25% + 涨停开盘占比20% + 竞价金额10%（各分量在分组间归一加权）。
          个股取该{groupLabel}最强前 5（排除 ST，含涨停开盘——只看强度不限是否可交易），按 竞价涨幅 &gt; 量比 &gt; 金额 排序。点击{groupLabel}行展开查看。
        </div>
        <div className="border rounded-lg bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">排名</th>
                <th className="px-3 py-2 text-left font-medium">{groupFull}</th>
                <th className="px-3 py-2 text-right font-medium">强度分</th>
                <th className="px-3 py-2 text-right font-medium">均涨幅</th>
                <th className="px-3 py-2 text-right font-medium">上涨家数</th>
                <th className="px-3 py-2 text-right font-medium">上涨占比</th>
                <th className="px-3 py-2 text-right font-medium">涨停开盘</th>
                <th className="px-3 py-2 text-right font-medium">竞价金额(万)</th>
                <th className="px-3 py-2 text-right font-medium">量比</th>
              </tr>
            </thead>
            <tbody>
              {sectors.map((s, i) => {
                const isOpen = expanded === s.industry;
                return (
                  <Fragment key={s.industry}>
                    <tr
                      className="border-t hover:bg-muted/30 cursor-pointer transition-colors"
                      onClick={() => setExpanded(isOpen ? null : s.industry)}
                    >
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2 font-medium">{s.industry}</td>
                      <td className="px-3 py-2 text-right font-bold text-primary">{s.score.toFixed(1)}</td>
                      <td className={`px-3 py-2 text-right font-medium ${s.avg_chg >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {s.avg_chg >= 0 ? "+" : ""}{s.avg_chg.toFixed(2)}%
                      </td>
                      <td className="px-3 py-2 text-right">{s.rising_n}/{s.n}</td>
                      <td className="px-3 py-2 text-right">{(s.rising_ratio * 100).toFixed(0)}%</td>
                      <td className="px-3 py-2 text-right font-medium text-amber-600">{s.limit_up_open_n}</td>
                      <td className="px-3 py-2 text-right">{s.total_amount_wan.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{s.avg_vol_ratio.toFixed(2)}</td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-muted/20">
                        <td colSpan={9} className="px-6 py-3">
                          <div className="text-xs text-muted-foreground mb-2">该{groupLabel}最强个股（Top {s.top_stocks.length}）</div>
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead className="text-xs text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1 text-left font-medium">代码</th>
                                  <th className="px-2 py-1 text-left font-medium">名称</th>
                                  <th className="px-2 py-1 text-right font-medium">竞价涨幅</th>
                                  <th className="px-2 py-1 text-right font-medium">量比</th>
                                  <th className="px-2 py-1 text-right font-medium">竞价金额(万)</th>
                                  <th className="px-2 py-1 text-left font-medium">板块/属性</th>
                                </tr>
                              </thead>
                              <tbody>
                                {s.top_stocks.map((st: any) => (
                                  <tr key={st.code} className="border-t border-muted/40">
                                    <td className="px-2 py-1 font-mono">{st.code}</td>
                                    <td className="px-2 py-1">
                                      <span className="flex items-center gap-1.5">
                                        {st.name}
                                        {st.limit_up_open && (
                                          <span className="px-1 py-0.5 text-[10px] font-semibold rounded bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
                                            涨停
                                          </span>
                                        )}
                                      </span>
                                    </td>
                                    <td className={`px-2 py-1 text-right font-medium ${st.chg >= 0 ? "text-red-600" : "text-green-600"}`}>
                                      {st.chg >= 0 ? "+" : ""}{st.chg.toFixed(2)}%
                                    </td>
                                    <td className="px-2 py-1 text-right">{st.vol_ratio != null ? st.vol_ratio.toFixed(2) : "—"}</td>
                                    <td className="px-2 py-1 text-right">{st.amount_wan.toLocaleString()}</td>
                                    <td className="px-2 py-1 text-xs text-muted-foreground">{st.board || ""}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  useEffect(() => { fetchDates(); }, []);

  useEffect(() => {
    if (selectedDate) {
      if (tab === "compare") fetchCompare();
      else if (tab === "expectation") fetchExpectData();
      else if (tab === "concept") fetchConceptAnalysis(selectedDate);
      else if (tab === "limitup") fetchLimitUp();
      else if (tab === "gapup") fetchGapUp();
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
            onClick={handleSnapshot}
            disabled={snapshotting}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-orange-600 text-white rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
          >
            <Camera className={`h-4 w-4 ${snapshotting ? "animate-spin" : ""}`} />
            {snapshotting ? "采集中..." : "采集快照"}
          </button>
          <button
            onClick={() => {
              if (!selectedDate) return;
              if (tab === "compare") fetchCompare();
              else if (tab === "expectation") fetchExpectData();
              else if (tab === "concept") fetchConceptAnalysis(selectedDate);
              else if (tab === "limitup") fetchLimitUp();
              else if (tab === "gapup") fetchGapUp();
            }}
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

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b">
        {[
          { key: "limitup" as const, label: "涨停竞价", icon: BarChart3 },
          { key: "gapup" as const, label: "跳空高开", icon: ArrowUpRight },
          { key: "compare" as const, label: "竞价对比", icon: TrendingDown },
          { key: "expectation" as const, label: "预期管理", icon: Eye },
          { key: "concept" as const, label: "竞价分析", icon: Sparkles },
          { key: "ai" as const, label: "AI分析", icon: Bot },
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

      {tab === "gapup" && gapUpData ? (
        <div className="space-y-4">
          {/* Header summary */}
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div className="border rounded-lg bg-card p-3">
              <div className="text-muted-foreground">竞价日期</div>
              <div className="text-xl font-bold">{gapUpData.date || "-"}</div>
            </div>
            <div className="border rounded-lg bg-card p-3">
              <div className="text-muted-foreground">跳空高开（≥3%）</div>
              <div className="text-xl font-bold text-red-600">{gapUpData.stocks.length}只</div>
            </div>
            <div className="border rounded-lg bg-card p-3">
              <div className="text-muted-foreground">跳空突破前高🔥</div>
              <div className="text-xl font-bold text-orange-600">
                {gapUpData.stocks.filter(s => s.gap_break_prev_high).length}只
              </div>
            </div>
            <div className="border rounded-lg bg-card p-3">
              <div className="text-muted-foreground">放量幅度（量比均值）</div>
              <div className="text-xl font-bold">
                {gapUpData.stocks.filter(s => s.vol_ratio).length > 0
                  ? (gapUpData.stocks.reduce((a, s) => a + (s.vol_ratio || 0), 0) /
                     gapUpData.stocks.filter(s => s.vol_ratio).length).toFixed(2)
                  : "-"}×
              </div>
            </div>
          </div>

          <div className="border rounded-lg bg-card overflow-hidden">
            <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2 justify-between">
              <div className="flex items-center gap-2">
                <ArrowUpRight className="h-4 w-4 text-red-500" />
                <h2 className="font-semibold">
                  跳空高开（竞价涨幅 3%~9%，量比≥1）
                </h2>
              </div>
              <span className="text-xs text-muted-foreground">按同花顺行业板块涨幅倒序</span>
            </div>
            {gapUpLoading ? (
              <div className="p-8 text-center text-muted-foreground animate-pulse">加载中...</div>
            ) : gapUpData.stocks.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">当日无符合条件的跳空高开股票</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">排名</th>
                      <th className="px-3 py-2 text-left font-medium">代码</th>
                      <th className="px-3 py-2 text-left font-medium">名称</th>
                      <th className="px-3 py-2 text-right font-medium">竞价价</th>
                      <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                      <th className="px-3 py-2 text-right font-medium">昨收</th>
                      <th className="px-3 py-2 text-right font-medium">昨日高点</th>
                      <th className="px-3 py-2 text-right font-medium">竞价量(手)</th>
                      <th className="px-3 py-2 text-right font-medium">竞价金额</th>
                      <th className="px-3 py-2 text-right font-medium">量比(vs昨)</th>
                      <th className="px-3 py-2 text-left font-medium">同花顺行业</th>
                      <th className="px-3 py-2 text-center font-medium">标签</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gapUpData.stocks.map((s, i) => (
                      <tr key={s.code} className={`border-t hover:bg-muted/30 ${
                        s.gap_break_prev_high ? "bg-orange-50/40 dark:bg-orange-950/20" : ""
                      }`}>
                        <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                        <td className="px-3 py-2 font-mono">{s.code}</td>
                        <td className="px-3 py-2 font-medium">{s.name}</td>
                        <td className="px-3 py-2 text-right font-medium text-red-600">
                          {s.auction_price.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right font-medium text-red-600">
                          +{s.chg_pct.toFixed(2)}%
                        </td>
                        <td className="px-3 py-2 text-right text-muted-foreground">
                          {s.prev_close.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right text-muted-foreground">
                          {s.prev_high != null ? s.prev_high.toFixed(2) : "-"}
                        </td>
                        <td className="px-3 py-2 text-right">{s.auction_vol.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">
                          {s.auction_amount_wan >= 10000
                            ? `${(s.auction_amount_wan / 10000).toFixed(2)}亿`
                            : `${s.auction_amount_wan.toFixed(0)}万`}
                        </td>
                        <td className={`px-3 py-2 text-right font-medium ${
                          s.vol_ratio == null ? "text-muted-foreground" :
                          s.vol_ratio >= 2 ? "text-red-600" :
                          s.vol_ratio >= 1.5 ? "text-orange-600" : "text-muted-foreground"
                        }`}>
                          {s.vol_ratio == null ? "-" : `${s.vol_ratio.toFixed(2)}×`}
                        </td>
                        <td className="px-3 py-2">
                          {s.top_industry ? (
                            <span className={`text-xs px-2 py-0.5 rounded ${
                              (s.top_industry_chg || 0) >= 3
                                ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400 font-medium"
                                : (s.top_industry_chg || 0) >= 1
                                ? "bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-400"
                                : (s.top_industry_chg || 0) < 0
                                ? "bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                                : "bg-muted/40 text-muted-foreground"
                            }`}>
                              {s.top_industry}
                              {s.top_industry_chg != null ? ` ${s.top_industry_chg >= 0 ? "+" : ""}${s.top_industry_chg.toFixed(2)}%` : ""}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {s.gap_break_prev_high ? (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 dark:bg-orange-950/50 dark:text-orange-400 font-medium">
                              突破前高🔥
                            </span>
                          ) : (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 dark:bg-red-950/20 dark:text-red-400">
                              跳空高开
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : tab === "compare" && compareData ? (
        <div className="space-y-6">
          {/* Search Bar */}
          <div className="border rounded-lg bg-card p-4">
            <div className="flex items-center gap-3">
              <Search className="h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
                placeholder="搜索股票代码或名称（回车搜索）"
                className="flex-1 border rounded-md px-3 py-1.5 text-sm bg-background"
              />
              <button
                onClick={handleSearch}
                disabled={searching || !searchKeyword.trim()}
                className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
              >
                <Search className={`h-4 w-4 ${searching ? "animate-spin" : ""}`} />
                {searching ? "搜索中..." : "搜索"}
              </button>
              {searchResults && (
                <button
                  onClick={() => { setSearchResults(null); setSearchKeyword(""); }}
                  className="px-3 py-1.5 text-sm border rounded-md hover:bg-muted"
                >
                  清除
                </button>
              )}
            </div>
          </div>

          {/* Search Results */}
          {searchResults && (
            <div className="border rounded-lg bg-card overflow-hidden">
              <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
                <Search className="h-4 w-4" />
                <h2 className="font-semibold">搜索结果: "{searchMeta?.keyword}"</h2>
                <span className="text-xs text-muted-foreground ml-auto">
                  共 {searchMeta?.total} 只  |  新增 {searchMeta?.new_count}  |  消失 {searchMeta?.gone_count}  |  放量 {searchMeta?.up}  |  缩量 {searchMeta?.down}
                </span>
              </div>
              {searchResults.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">未找到匹配股票</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">代码</th>
                        <th className="px-3 py-2 text-left font-medium">名称</th>
                        <th className="px-3 py-2 text-right font-medium">今竞价量</th>
                        <th className="px-3 py-2 text-right font-medium">昨竞价量</th>
                        <th className="px-3 py-2 text-right font-medium">变化%</th>
                        <th className="px-3 py-2 text-right font-medium">今金额(万)</th>
                        <th className="px-3 py-2 text-right font-medium">竞价价</th>
                        <th className="px-3 py-2 text-center font-medium">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {searchResults.map((r) => {
                        const pct = r.is_new ? 999 : r.vol_pct;
                        const status = r.is_new ? "新增" : r.is_gone ? "消失" : pct > 120 ? "放量↑" : pct < 80 ? "缩量↓" : "持平→";
                        const isHighlight = !r.is_new && !r.is_gone && pct > 150;
                        return (
                          <tr key={r.code} className={`border-t hover:bg-muted/30 ${isHighlight ? "bg-red-50/30" : ""}`}>
                            <td className="px-3 py-2 font-mono">{r.code}</td>
                            <td className="px-3 py-2 font-medium">{r.name}</td>
                            <td className="px-3 py-2 text-right">{r.vol_today > 0 ? r.vol_today.toLocaleString() : "—"}</td>
                            <td className="px-3 py-2 text-right text-muted-foreground">{r.vol_prev > 0 ? r.vol_prev.toLocaleString() : "—"}</td>
                            <td className={`px-3 py-2 text-right font-medium ${r.is_new ? "text-blue-600" : r.is_gone ? "text-muted-foreground" : r.vol_pct > 100 ? "text-red-600" : "text-green-600"}`}>
                              {r.is_new ? "NEW" : r.is_gone ? "—" : `${r.vol_pct >= 0 ? "+" : ""}${r.vol_pct.toFixed(1)}%`}
                              {isHighlight && " ★"}
                            </td>
                            <td className="px-3 py-2 text-right">{r.amt_today > 0 ? r.amt_today.toLocaleString() : "—"}</td>
                            <td className="px-3 py-2 text-right">{r.price_today > 0 ? r.price_today.toFixed(2) : "—"}</td>
                            <td className="px-3 py-2 text-center">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                status === "新增" ? "bg-blue-100 text-blue-700" :
                                status === "消失" ? "bg-gray-100 text-gray-500" :
                                status === "放量↑" ? "bg-red-100 text-red-700" :
                                status === "缩量↓" ? "bg-green-100 text-green-700" :
                                "bg-gray-50 text-gray-400"
                              }`}>{status}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

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
                      <td className="px-3 py-2 text-right">{s.vol_today.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{s.vol_prev.toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${volClass(s.vol_chg)}`}>
                        {(s.vol_chg > 0 ? "+" : "") + Math.abs(s.vol_chg).toLocaleString()}
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
                  onClick={() => setAnalysisSource("ths_industry")}
                  className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                    analysisSource === "ths_industry"
                      ? "bg-primary text-primary-foreground"
                      : "border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  最强行业
                </button>
                <button
                  onClick={() => setAnalysisSource("ths_concept")}
                  className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                    analysisSource === "ths_concept"
                      ? "bg-primary text-primary-foreground"
                      : "border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  最强概念
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
            <SectorStrengthView
              source={analysisSource}
              sectors={sectorData}
              loading={conceptLoading}
              expanded={expandedSector}
              setExpanded={setExpandedSector}
            />

        </div>
      ) : tab === "ai" ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2 justify-between">
            <div className="text-sm text-muted-foreground">
              {selectedDate ? `分析日期: ${selectedDate}` : "请先选择日期"}
            </div>
            <div className="flex items-center gap-2">
              {/* 发送到网页LLM */}
              <div className="relative">
                <button
                  onClick={() => setShowLlmMenu(!showLlmMenu)}
                  disabled={!!askTarget}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 text-white rounded-md hover:bg-emerald-700 transition-colors disabled:opacity-60"
                >
                  <ExternalLink className={`h-4 w-4 ${askTarget ? "animate-pulse" : ""}`} />
                  {askTarget
                    ? `正在获取 ${askTarget === "all" ? "全部" : LLM_OPTIONS.find(o => o.key === askTarget)?.label ?? ""} 回答...`
                    : "发送到网页LLM"}
                  <ChevronDown className="h-3 w-3" />
                </button>
                {showLlmMenu && !askTarget && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setShowLlmMenu(false)} />
                    <div className="absolute right-0 z-50 mt-1 w-52 bg-popover border rounded-md shadow-md">
                      <button
                        onClick={handleSendAll}
                        disabled={sendingAll}
                        className="w-full text-left px-3 py-2 text-sm font-medium text-emerald-600 hover:bg-muted transition-colors disabled:opacity-50"
                      >
                        一键发送（豆包 + DeepSeek）
                      </button>
                      <div className="border-t my-1" />
                      {LLM_OPTIONS.map((opt) => (
                        <button
                          key={opt.key}
                          onClick={() => handleSendToLlm(opt.key, opt.label, opt.url)}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors"
                        >
                          {opt.label}
                        </button>
                      ))}
                      <div className="border-t my-1" />
                      {LLM_OPTIONS.map((opt) => (
                        <button
                          key={`login-${opt.key}`}
                          onClick={() => handleLlmLogin(opt.key, opt.label)}
                          className="w-full text-left px-3 py-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors last:rounded-b-md"
                        >
                          首次使用：登录{opt.label}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
              {/* 内置AI分析 */}
              <button
                onClick={fetchAiAnalysis}
                disabled={aiLoading || !selectedDate}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-colors disabled:opacity-50"
              >
                <Bot className={`h-4 w-4 ${aiLoading ? "animate-pulse" : ""}`} />
                {aiLoading ? "AI分析中..." : "开始AI分析"}
              </button>
            </div>
          </div>

          {/* 将发送给网页LLM的内容预览（模板 + 本地实盘数据） */}
          <div className="border rounded-lg bg-card p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">将发送给豆包的内容（模板 + 本地实盘数据）</p>
              <div className="flex items-center gap-3">
                <button onClick={() => fetchAuctionPreview(selectedStage, true)} className="text-xs text-muted-foreground hover:text-foreground">
                  刷新
                </button>
                {auctionPreview && (
                  <button
                    onClick={() => navigator.clipboard.writeText(auctionPreview)}
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >
                    复制
                  </button>
                )}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              选择阶段后下方展示该阶段内容；点击发送即把当前阶段内容发给豆包/DeepSeek。
            </p>
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground">阶段：</label>
              <select
                value={selectedStage}
                onChange={(e) => setSelectedStage(e.target.value)}
                className="text-sm border rounded-md px-2 py-1 bg-background"
              >
                <option value="auto">请选择阶段（手动）</option>
                <option value="0">① 盘前</option>
                <option value="1">② 09:25 情绪总开关</option>
                <option value="2">③ 09:35 验证资金态度</option>
                <option value="3">④ 09:45 确认主线合力</option>
              </select>
              <label
                className={`flex items-center gap-1 text-xs text-muted-foreground cursor-pointer ml-2 ${selectedStage === "0" ? "opacity-50" : ""}`}
                title={selectedStage === "0" ? "盘前不附文件" : "附带竞价数据 xlsx 作为附件"}
              >
                <input
                  type="checkbox"
                  checked={useFile}
                  disabled={selectedStage === "0"}
                  onChange={(e) => setUseFile(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                传文件(竞价数据xlsx)
              </label>
            </div>
            <textarea
              value={auctionPreview}
              readOnly
              placeholder={previewLoading ? "加载中…（正在从本地数据库 + 腾讯实时行情取数）" : "请先在上方选择阶段（①~④），预览将在此显示"}
              className="w-full h-72 p-3 text-xs font-mono border rounded-md bg-zinc-950 text-zinc-200 resize-y focus:outline-none"
            />
          </div>

          {aiLoading && (
            <div className="border rounded-lg bg-card p-8 text-center">
              <Bot className="h-8 w-8 mx-auto mb-3 animate-pulse text-primary" />
              <p className="text-sm text-muted-foreground">
                正在调用 LLM 分析竞价数据，约需 30~60 秒...
              </p>
            </div>
          )}

          {!aiLoading && aiError && (
            <div className="border border-red-300 rounded-lg bg-red-50 dark:bg-red-950/20 p-4">
              <p className="text-sm text-red-600">
                <span className="font-medium">分析失败: </span>
                {aiError}
              </p>
            </div>
          )}

          {!aiLoading && aiReport && (
            <div className="border rounded-lg bg-card p-6">
              <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">
                {aiReport}
              </div>
            </div>
          )}

          {!aiLoading && !aiReport && !aiError && (
            <div className="border rounded-lg bg-card p-8 text-center text-muted-foreground">
              <Bot className="h-8 w-8 mx-auto mb-3 opacity-40" />
              <p className="text-sm">点击"开始AI分析"调用内置LLM（若已用"一键发送"收到豆包/DeepSeek回答，将自动综合两家观点）；或点击"发送到网页LLM"将三信号框架复制到豆包/DeepSeek</p>
            </div>
          )}

          {/* 网页LLM回答粘贴区 */}
          <div className="border rounded-lg bg-card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">网页LLM回答</p>
              {pastedAnswer && (
                <button
                  onClick={() => setPastedAnswer("")}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  清空
                </button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              从豆包/DeepSeek复制回答后，粘贴到下方（或用上方"一键发送"自动获取）
            </p>
            {pastedAnswer ? (
              <div className="border rounded-md p-4 prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm">
                {pastedAnswer}
              </div>
            ) : (
              <textarea
                value={pastedAnswer}
                onChange={(e) => setPastedAnswer(e.target.value)}
                placeholder="在此粘贴网页LLM的回答..."
                className="w-full h-64 p-3 text-sm border rounded-md bg-background resize-y focus:outline-none focus:ring-1 focus:ring-ring"
              />
            )}
          </div>

          {/* 一键发送的网页LLM回答（豆包 + DeepSeek） */}
          {webAnswers.length > 0 && (
            <div className="space-y-3">
              {webAnswers.map((wa) => (
                <div key={wa.target} className="border rounded-lg bg-card p-4">
                  <p className="text-xs font-medium text-muted-foreground mb-2">{wa.label} 回答</p>
                  <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm">
                    {wa.answer}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 自动化进度日志 */}
          {askLogs.length > 0 && (
            <div
              ref={logBoxRef}
              className="border rounded-lg bg-zinc-950 text-zinc-300 font-mono text-xs p-3 max-h-48 overflow-y-auto"
            >
              {askLogs.map((line, i) => (
                <div key={i} className={line.includes("✗") ? "text-red-400" : line.includes("✓") ? "text-emerald-400" : ""}>
                  {line}
                </div>
              ))}
              {askTarget && <div className="animate-pulse text-zinc-500">▌ 运行中...</div>}
            </div>
          )}
        </div>
      ) : (
        /* 涨停竞价对比 */
        <div className="space-y-4">
          {/* Sub-tabs */}
          <div className="flex items-center gap-2">
            {[
              { key: "both" as const, label: "双涨停", countKey: "both_count" as const },
              { key: "yesterday" as const, label: "昨日涨停", countKey: "prev_count" as const },
              { key: "today" as const, label: "竞价涨停", countKey: "today_count" as const },
            ].map(({ key, label, countKey }) => (
              <button
                key={key}
                onClick={() => setLimitUpSubTab(key)}
                className={`flex items-center gap-1 px-3 py-1.5 text-sm rounded-md transition-colors ${
                  limitUpSubTab === key
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted/40 text-muted-foreground hover:text-foreground"
                }`}
              >
                {label}
                <span className="text-xs opacity-70">
                  ({limitUpData ? (key === "today" ? limitUpData.both_limitup.length + limitUpData.today_limitup.length : limitUpData[countKey]) : 0})
                </span>
              </button>
            ))}
          </div>

          {limitUpLoading ? (
            <div className="py-12 text-center text-muted-foreground">加载中...</div>
          ) : !limitUpData ? (
            <div className="py-12 text-center text-muted-foreground">请先选择日期</div>
          ) : (
            <div className="border rounded-lg bg-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">代码</th>
                      <th className="px-3 py-2 text-left font-medium">名称</th>
                      <th className="px-3 py-2 text-left font-medium">概念</th>
                      <th className="px-3 py-2 text-right font-medium">今竞价量</th>
                      <th className="px-3 py-2 text-right font-medium">昨竞价量</th>
                      <th className="px-3 py-2 text-right font-medium">{limitUpSubTab === "yesterday" ? "实时涨幅" : "量变化"}</th>
                      <th className="px-3 py-2 text-right font-medium">量比</th>
                      <th className="px-3 py-2 text-right font-medium">今竞价额</th>
                      <th className="px-3 py-2 text-right font-medium">昨竞价额</th>
                      <th className="px-3 py-2 text-right font-medium">竞价涨幅</th>
                      <th className="px-3 py-2 text-center font-medium">连板</th>
                      <th className="px-3 py-2 text-center font-medium">昨封板/预期</th>
                      <th className="px-3 py-2 text-right font-medium">竞价量能</th>
                      <th className="px-3 py-2 text-center font-medium">预期组合</th>
                      <th className="px-3 py-2 text-left font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      let items: any[] = [];
                      if (limitUpSubTab === "both") items = limitUpData.both_limitup;
                      else if (limitUpSubTab === "yesterday") items = limitUpData.prev_limitup;
                      else items = [...limitUpData.both_limitup, ...limitUpData.today_limitup];
                      return items.length > 0 ? items.map((s: any) => (
                        <tr key={s.code} className="border-t hover:bg-muted/30 transition-colors">
                          <td className="px-3 py-2 font-mono">{s.code}</td>
                          <td className="px-3 py-2">{s.name}</td>
                          <td className="px-3 py-2 max-w-[240px]">
                            {s.concepts && s.concepts.length > 0 ? (
                              <span className="flex flex-wrap gap-1">
                                {s.concepts.slice(0, 4).map((c: string) => (
                                  <span key={c} className="text-xs px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground whitespace-nowrap">{c}</span>
                                ))}
                                {s.concepts.length > 4 && (
                                  <span className="text-xs text-muted-foreground">+{s.concepts.length - 4}</span>
                                )}
                              </span>
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right font-medium">{s.vol_today.toLocaleString()}</td>
                          <td className="px-3 py-2 text-right text-muted-foreground">{s.vol_prev > 0 ? s.vol_prev.toLocaleString() : "-"}</td>
                          {limitUpSubTab === "yesterday" ? (
                            <td className={`px-3 py-2 text-right font-medium ${(s.realtime_chg_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                              {s.realtime_chg_pct != null ? `${s.realtime_chg_pct >= 0 ? "+" : ""}${s.realtime_chg_pct.toFixed(2)}%` : "-"}
                            </td>
                          ) : (
                            <td className={`px-3 py-2 text-right font-medium ${s.vol_chg > 0 ? "text-red-600" : s.vol_chg < 0 ? "text-green-600" : ""}`}>
                              {s.vol_chg > 0 ? "+" : ""}{s.vol_chg.toLocaleString()}
                            </td>
                          )}
                          <td className={`px-3 py-2 text-right font-medium ${s.vol_pct >= 999 ? "" : s.vol_pct >= 100 ? "text-red-600" : "text-green-600"}`}>
                            {s.vol_pct >= 999 ? "新" : `${s.vol_pct.toFixed(0)}%`}
                          </td>
                          <td className="px-3 py-2 text-right">{s.amt_today > 0 ? s.amt_today.toLocaleString() : "-"}</td>
                          <td className="px-3 py-2 text-right text-muted-foreground">{s.amt_prev > 0 ? s.amt_prev.toLocaleString() : "-"}</td>
                          <td className={`px-3 py-2 text-right font-medium ${(s.auction_chg_today ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                            {s.auction_chg_today != null ? `${s.auction_chg_today >= 0 ? "+" : ""}${s.auction_chg_today.toFixed(2)}%` : "-"}
                          </td>
                          {(() => {
                            const biz = s.auction_expectation || null;
                            if (!biz) {
                              return (
                                <>
                                  <td colSpan={5} className="px-3 py-2 text-center text-muted-foreground">—</td>
                                </>
                              );
                            }
                            const combo = biz.combo || {};
                            const colorMap: Record<string, string> = {
                              red: "bg-red-600/15 text-red-600 border-red-600/30",
                              orange: "bg-orange-600/15 text-orange-600 border-orange-600/30",
                              blue: "bg-blue-600/15 text-blue-600 border-blue-600/30",
                              gray: "bg-muted text-muted-foreground border-muted",
                              purple: "bg-purple-600/15 text-purple-600 border-purple-600/30",
                              black: "bg-zinc-900 text-zinc-100 border-zinc-700",
                            };
                            const badgeCls = colorMap[combo.color] || colorMap.gray;
                            return (
                              <>
                                <td className="px-3 py-2 text-center font-mono">{biz.consec_boards > 0 ? biz.consec_boards : "-"}</td>
                                <td className="px-3 py-2 text-center">
                                  <span className="text-xs text-muted-foreground">{biz.band || "-"}</span>
                                  <span className="block text-[10px] text-muted-foreground/70">{biz.first_seal ? `${biz.first_seal.slice(0, 2)}:${biz.first_seal.slice(2, 4)}` : ""}</span>
                                </td>
                                <td className="px-3 py-2 text-right font-medium">
                                  {biz.vol_pct_auction != null ? (
                                    <span className={biz.vol_level === "达标" ? "text-red-600" : "text-muted-foreground"}>
                                      {biz.vol_pct_auction.toFixed(1)}%
                                    </span>
                                  ) : "-"}
                                </td>
                                <td className="px-3 py-2 text-center">
                                  {combo.combo ? (
                                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${badgeCls}`}>
                                      {combo.combo} {combo.label}
                                    </span>
                                  ) : <span className="text-muted-foreground text-xs">—</span>}
                                  <span className="block text-[10px] text-muted-foreground/70">{biz.price_level}</span>
                                </td>
                                <td className="px-3 py-2 text-left text-xs text-muted-foreground">{combo.action || "-"}</td>
                              </>
                            );
                          })()}
                        </tr>
                      )) : (
                        <tr>
                          <td colSpan={15} className="px-3 py-8 text-center text-muted-foreground">暂无数据</td>
                        </tr>
                      );
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Summary stats */}
          {limitUpData && (
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div className="border rounded-lg bg-card p-3 text-center">
                <div className="text-muted-foreground">昨日涨停</div>
                <div className="text-xl font-bold">{limitUpData.prev_count}只</div>
              </div>
              <div className="border rounded-lg bg-card p-3 text-center">
                <div className="text-muted-foreground">竞价涨停</div>
                <div className="text-xl font-bold">{limitUpData.today_count}只</div>
              </div>
              <div className="border rounded-lg bg-card p-3 text-center">
                <div className="text-muted-foreground">双涨停</div>
                <div className="text-xl font-bold">{limitUpData.both_count}只</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

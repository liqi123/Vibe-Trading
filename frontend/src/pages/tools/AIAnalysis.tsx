import { useState, type ReactNode } from "react";
import { Brain, Loader2, CheckCircle2, XCircle, TrendingUp, TrendingDown } from "lucide-react";
import { api } from "@/lib/api";

interface StockReason {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  buy_reasons: string[];
  no_buy_reasons: string[];
  error?: string;
  raw?: string;
}

function pctColor(pct: number): string {
  if (pct > 0) return "text-red-500"; // A股惯例：涨=红
  if (pct < 0) return "text-green-500"; // 跌=绿
  return "text-muted-foreground";
}

function pctText(pct: number): string {
  const s = pct > 0 ? "+" : "";
  return `${s}${pct.toFixed(2)}%`;
}

function ReasonColumn({
  title,
  icon,
  items,
  accent,
}: {
  title: string;
  icon: ReactNode;
  items: string[];
  accent: string;
}) {
  return (
    <div className="flex-1 min-w-0 space-y-2">
      <div className={`flex items-center gap-1.5 font-semibold text-sm ${accent}`}>
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground">暂无</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((it, i) => (
            <li
              key={i}
              className="text-xs leading-relaxed border-l-2 pl-2"
              style={{ borderColor: accent === "text-red-500" ? "#ef4444" : "#22c55e" }}
            >
              {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AIAnalysis() {
  const [codes, setCodes] = useState("");
  const [results, setResults] = useState<StockReason[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleAnalyze = async () => {
    const codeList = codes.split(/[,，\s]+/).filter(Boolean);
    if (codeList.length === 0) return;
    setLoading(true);
    setError("");
    setResults([]);
    try {
      const data = await api.tools.post<any>("/ai/reasons", { codes: codeList });
      if (data && data.error) {
        setError(data.error);
      } else if (data && Array.isArray(data.stocks)) {
        setResults(data.stocks);
      } else {
        setError("分析失败：返回格式异常");
      }
    } catch (e: any) {
      setError(`请求失败: ${e?.message || e}`);
    }
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">AI 分析</h1>
        <p className="text-sm text-muted-foreground mt-1">
          输入股票代码，获取实时价格与「买 / 不买」双向理由
        </p>
      </div>

      <div className="border rounded-lg p-5 bg-card space-y-4">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-purple-500" />
          <h3 className="font-semibold">股票分析</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          输入股票代码（逗号分隔），AI 结合实时行情给出买与不买的双向理由
        </p>
        <input
          value={codes}
          onChange={(e) => setCodes(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
          placeholder="如: sh600519, sz000725, 300717"
          className="w-full px-3 py-2 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30"
        />
        <button
          onClick={handleAnalyze}
          disabled={loading || !codes.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
          {loading ? "分析中..." : "开始分析"}
        </button>
      </div>

      {error && (
        <div className="border border-red-300 bg-red-50 text-red-700 rounded-lg p-4 text-sm">
          {error}
        </div>
      )}

      {results.map((s) => (
        <div key={s.code} className="border rounded-lg bg-card p-5 space-y-4">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold">{s.name || s.code}</span>
              <span className="text-xs text-muted-foreground">{s.code}</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-semibold tabular-nums">{s.price.toFixed(2)}</span>
              <span className={`text-sm font-medium flex items-center gap-0.5 ${pctColor(s.change_pct)}`}>
                {s.change_pct > 0 ? (
                  <TrendingUp className="h-3.5 w-3.5" />
                ) : s.change_pct < 0 ? (
                  <TrendingDown className="h-3.5 w-3.5" />
                ) : null}
                {pctText(s.change_pct)}
              </span>
            </div>
          </div>
          <div className="text-[11px] text-muted-foreground">实时价格（非交易时段为最近收盘价）</div>

          {s.error ? (
            <div className="text-xs text-red-600">⚠️ {s.error}</div>
          ) : (
            <div className="flex flex-col sm:flex-row gap-4">
              <ReasonColumn
                title="买它的理由"
                icon={<CheckCircle2 className="h-4 w-4" />}
                items={s.buy_reasons}
                accent="text-red-500"
              />
              <div className="hidden sm:block w-px bg-border" />
              <ReasonColumn
                title="不买它的理由"
                icon={<XCircle className="h-4 w-4" />}
                items={s.no_buy_reasons}
                accent="text-green-500"
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

import { useState } from "react";
import { Brain, Loader2, Save, X } from "lucide-react";
import { api } from "@/lib/api";

export interface DimDef {
  key: string; // analysis 里的维度键，如 "梯队"
  label: string; // 展示名，如 "梯队完整"
}

interface Props {
  title: string;
  scope: "mainlines" | "stocks" | "cycle";
  objectKey: string; // 主线名或股票代码
  dims: DimDef[];
  analysis: any; // 缓存里的 analysis 字段
  aiCtx: Record<string, any>; // 传给 LLM 的上下文（主线或个股 dict）
  cycle?: string;
  defaultOpen?: boolean;
  onUpdated: (scope: "mainlines" | "stocks" | "cycle", objectKey: string, dimension: string, text: string) => void;
}

export function SentimentAnalysisBlock({ title, scope, objectKey, dims, analysis, aiCtx, cycle, defaultOpen, onUpdated }: Props) {
  const [open, setOpen] = useState<boolean>(!!defaultOpen);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [msg, setMsg] = useState<string>("");

  const savedNode = (dim: string) => analysis?.[scope]?.[objectKey]?.[dim] || {};
  const displayText = (dim: string) => edits[dim] ?? savedNode(dim)?.manual ?? savedNode(dim)?.ai ?? "";

  const runAi = async (dim: string) => {
    setLoadingKey(dim);
    setMsg("");
    try {
      const body: Record<string, any> = { scope, key: objectKey, dimension: dim, cycle };
      if (scope === "mainlines") body.mainline = aiCtx;
      else if (scope === "stocks") body.stock = aiCtx;
      else if (scope === "cycle") body.breadth = aiCtx?.breadth || {};
      const res = await api.tools.post<any>("/sentiment/analysis/ai", body);
      if (res?.ok) {
        setEdits((p) => ({ ...p, [dim]: res.analysis }));
      } else {
        setMsg(`AI分析失败: ${res?.error || ""}`);
      }
    } catch (e: any) {
      setMsg(`AI分析失败: ${e?.message || String(e)}`);
    } finally {
      setLoadingKey(null);
    }
  };

  const save = async (dim: string) => {
    const text = (edits[dim] ?? "").trim();
    setSavingKey(dim);
    setMsg("");
    try {
      const res = await api.tools.post<any>("/sentiment/analysis/save", {
        scope,
        key: objectKey,
        dimension: dim,
        text,
      });
      if (res?.ok) {
        setEdits((p) => {
          const n = { ...p };
          delete n[dim];
          return n;
        });
        onUpdated(scope, objectKey, dim, text);
        setMsg(`「${dim}」已保存`);
      } else {
        setMsg(`保存失败: ${res?.error || ""}`);
      }
    } catch (e: any) {
      setMsg(`保存失败: ${e?.message || String(e)}`);
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="mt-2 rounded-lg border bg-background/40 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-left text-sm font-medium hover:bg-muted/40"
      >
        <span>{title}</span>
        <span className="text-xs text-muted-foreground">{open ? "收起" : "展开逐维度分析"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-3">
          {dims.map((d) => (
            <div key={d.key} className="border rounded-md p-2.5">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold">{d.label}</span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => runAi(d.key)}
                    disabled={loadingKey === d.key}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 transition-colors"
                  >
                    {loadingKey === d.key ? <Loader2 className="h-3 w-3 animate-spin" /> : <Brain className="h-3 w-3" />}
                    {loadingKey === d.key ? "分析中" : "AI分析"}
                  </button>
                  <button
                    onClick={() => save(d.key)}
                    disabled={savingKey === d.key || !(edits[d.key] ?? "").trim()}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-40 transition-colors"
                  >
                    {savingKey === d.key ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                    保存
                  </button>
                </div>
              </div>
              <textarea
                value={displayText(d.key)}
                onChange={(e) => setEdits((p) => ({ ...p, [d.key]: e.target.value }))}
                placeholder={`输入「${d.label}」的人工分析，或点 AI分析 生成...`}
                className="w-full p-2 border rounded text-sm bg-background min-h-[56px] resize-y"
              />
              {displayText(d.key) && savedNode(d.key)?.ai && !edits[d.key] && !savedNode(d.key)?.manual && (
                <div className="mt-1 text-[11px] text-violet-600">来源：AI 生成</div>
              )}
            </div>
          ))}
          {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
          <button
            onClick={() => setOpen(false)}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary"
          >
            <X className="h-3 w-3" /> 收起
          </button>
        </div>
      )}
    </div>
  );
}

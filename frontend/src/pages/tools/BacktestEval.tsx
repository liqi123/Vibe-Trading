import { useState } from "react";
import { TrendingUp, Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";

interface Pick {
  code: string;
  date: string;
}

export function BacktestEval() {
  const [picks, setPicks] = useState<Pick[]>([{ code: "", date: "" }]);
  const [evalDays, setEvalDays] = useState(5);
  const [report, setReport] = useState("");
  const [loading, setLoading] = useState(false);

  const addPick = () => setPicks([...picks, { code: "", date: "" }]);
  const removePick = (i: number) => setPicks(picks.filter((_, idx) => idx !== i));
  const updatePick = (i: number, field: keyof Pick, val: string) => {
    const next = [...picks];
    next[i] = { ...next[i], [field]: val };
    setPicks(next);
  };

  const handleEval = async () => {
    const valid = picks.filter((p) => p.code && p.date);
    if (valid.length === 0) return;
    setLoading(true);
    setReport("");
    try {
      const data = await api.tools.post<any>("/backtest/eval", { picks: valid, eval_days: evalDays });
      setReport(data.report || data.error || "评估失败");
    } catch (e: any) {
      setReport(`请求失败: ${e.message}`);
    }
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">回测评估</h1>
        <p className="text-sm text-muted-foreground mt-1">评估选股后续N日收益表现</p>
      </div>

      <div className="border rounded-lg p-5 bg-card space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-blue-500" />
            <h3 className="font-semibold">选股评估</h3>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground">评估天数</label>
            <input type="number" value={evalDays} onChange={(e) => setEvalDays(parseInt(e.target.value) || 5)}
              className="w-16 px-2 py-1 text-sm border rounded bg-background text-center" />
          </div>
        </div>

        <div className="space-y-2">
          {picks.map((p, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={p.code} onChange={(e) => updatePick(i, "code", e.target.value)}
                placeholder="代码 sh600519" className="flex-1 px-3 py-1.5 text-sm border rounded bg-background" />
              <input type="date" value={p.date} onChange={(e) => updatePick(i, "date", e.target.value)}
                className="px-3 py-1.5 text-sm border rounded bg-background" />
              {picks.length > 1 && (
                <button onClick={() => removePick(i)} className="p-1 text-muted-foreground hover:text-red-600">
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <button onClick={addPick}
            className="flex items-center gap-1 px-3 py-1.5 text-sm border rounded-md hover:bg-muted">
            <Plus className="h-3.5 w-3.5" />添加
          </button>
          <button onClick={handleEval} disabled={loading}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <TrendingUp className="h-4 w-4" />}
            {loading ? "评估中..." : "开始评估"}
          </button>
        </div>
      </div>

      {report && (
        <div className="border rounded-lg bg-card p-5">
          <h3 className="font-semibold mb-3">评估报告</h3>
          <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed">{report}</pre>
        </div>
      )}
    </div>
  );
}

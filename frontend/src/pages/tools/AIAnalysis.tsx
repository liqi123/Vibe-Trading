import { useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

export function AIAnalysis() {
  const [codes, setCodes] = useState("");
  const [report, setReport] = useState("");
  const [loading, setLoading] = useState(false);

  const handleAnalyze = async () => {
    const codeList = codes.split(/[,，\s]+/).filter(Boolean);
    if (codeList.length === 0) return;
    setLoading(true);
    setReport("");
    try {
      const data = await api.tools.post<any>("/ai/analyze", { codes: codeList });
      setReport(data.report || data.error || "分析失败");
    } catch (e: any) {
      setReport(`请求失败: ${e.message}`);
    }
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">AI 分析</h1>
        <p className="text-sm text-muted-foreground mt-1">LLM 驱动的个股分析</p>
      </div>

      <div className="border rounded-lg p-5 bg-card space-y-4">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-purple-500" />
          <h3 className="font-semibold">股票分析</h3>
        </div>
        <p className="text-xs text-muted-foreground">输入股票代码（逗号分隔），AI 将生成买卖建议</p>
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

      {report && (
        <div className="border rounded-lg bg-card p-5">
          <h3 className="font-semibold mb-3">分析报告</h3>
          <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed">{report}</pre>
        </div>
      )}
    </div>
  );
}

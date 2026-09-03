import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { FileText, RefreshCw } from "lucide-react";

interface Props {
  /** 日志子目录：stock_selection | ai_analysis */
  subdir: string;
  /** 日志名：sentiment_leader | auction_ai_analysis */
  name: string;
  title?: string;
  /** 自动刷新间隔（毫秒），0 表示不轮询 */
  autoRefresh?: number;
}

/** 读取后端 logs/<subdir>/<name>_YYYYMMDD.log 并展示（供前端「运行日志」面板）。 */
export function RunLogPanel({ subdir, name, title = "运行日志", autoRefresh = 0 }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.tools.get<any>(
        `/logs?subdir=${encodeURIComponent(subdir)}&name=${encodeURIComponent(name)}&tail=300`,
      );
      if (res?.ok) {
        setLines(res.lines || []);
        setPath(res.path || "");
      } else {
        setError(res?.error || "暂无日志");
        setLines([]);
      }
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [subdir, name]);

  useEffect(() => {
    if (!open) return;
    load();
    if (autoRefresh > 0) {
      const t = setInterval(load, autoRefresh);
      return () => clearInterval(t);
    }
  }, [open, load, autoRefresh]);

  return (
    <div className="border rounded-lg bg-card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium hover:bg-muted/40 transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <FileText className="h-4 w-4 text-muted-foreground" />
          {title}
        </span>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          {open && <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />}
          {open ? "收起" : "展开"}
        </span>
      </button>
      {open && (
        <div className="border-t px-3 py-2">
          {error && <p className="text-xs text-muted-foreground mb-1">{error}</p>}
          <pre className="max-h-64 overflow-auto text-xs font-mono whitespace-pre-wrap leading-relaxed bg-muted/40 rounded p-2">
            {lines.length ? lines.join("\n") : loading ? "加载中…" : "暂无日志内容"}
          </pre>
          {path && <p className="mt-1 text-[11px] text-muted-foreground truncate">{path}</p>}
        </div>
      )}
    </div>
  );
}

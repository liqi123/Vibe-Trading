import { useEffect, useState } from "react";
import { Clock, Plus, Trash2, RefreshCw, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

interface ScheduledJob {
  id: string;
  prompt: string;
  schedule: string;
  status: string;
  next_run_at?: string;
  last_run_at?: string;
}

export function ScheduledTasks() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newPrompt, setNewPrompt] = useState("");
  const [newSchedule, setNewSchedule] = useState("");
  const [creating, setCreating] = useState(false);

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const data = await api.tools.get<any>("/scheduled-runs");
      setJobs(data.jobs || []);
    } catch (e) { console.error('Failed to fetch jobs:', e); }
    setLoading(false);
  };

  useEffect(() => { fetchJobs(); }, []);

  const handleCreate = async () => {
    if (!newPrompt.trim() || !newSchedule.trim()) return;
    setCreating(true);
    try {
      await api.tools.post<any>("/scheduled-runs", { prompt: newPrompt.trim(), schedule: newSchedule.trim() });
      setNewPrompt("");
      setNewSchedule("");
      setShowAdd(false);
      fetchJobs();
    } catch (e) { console.error('Failed to create job:', e); }
    setCreating(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.tools.del<any>(`/scheduled-runs/${id}`);
      fetchJobs();
    } catch (e) { console.error('Failed to delete job:', e); }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">定时任务</h1>
          <p className="text-sm text-muted-foreground mt-1">管理定时研究任务</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowAdd(!showAdd)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90">
            <Plus className="h-4 w-4" />新建
          </button>
          <button onClick={fetchJobs} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted disabled:opacity-50">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />刷新
          </button>
        </div>
      </div>

      {/* Create Form */}
      {showAdd && (
        <div className="border rounded-lg p-5 bg-card space-y-4">
          <h3 className="font-semibold">新建定时任务</h3>
          <div>
            <label className="text-xs text-muted-foreground">研究提示词</label>
            <input value={newPrompt} onChange={(e) => setNewPrompt(e.target.value)}
              placeholder="如: 分析最近一周北向资金流入的板块"
              className="w-full mt-1 px-3 py-2 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">调度计划 (cron 或 interval-ms)</label>
            <input value={newSchedule} onChange={(e) => setNewSchedule(e.target.value)}
              placeholder="如: 0 9 * * 1-5 或 3600000"
              className="w-full mt-1 px-3 py-2 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={creating || !newPrompt.trim() || !newSchedule.trim()}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50">
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {creating ? "创建中..." : "创建"}
            </button>
            <button onClick={() => setShowAdd(false)}
              className="px-4 py-2 text-sm border rounded-md hover:bg-muted">取消</button>
          </div>
        </div>
      )}

      {/* Jobs List */}
      <div className="border rounded-lg bg-card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-muted-foreground">加载中...</div>
        ) : jobs.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">暂无定时任务</div>
        ) : (
          <div className="divide-y">
            {jobs.map((job) => (
              <div key={job.id} className="px-5 py-4 flex items-start justify-between gap-4 hover:bg-muted/30">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="text-sm font-medium truncate">{job.prompt}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      job.status === "active" ? "bg-green-100 text-green-700" :
                      job.status === "paused" ? "bg-yellow-100 text-yellow-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {job.status}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    调度: {job.schedule}
                    {job.next_run_at && ` · 下次: ${job.next_run_at}`}
                  </div>
                </div>
                <button onClick={() => handleDelete(job.id)}
                  className="p-1.5 text-muted-foreground hover:text-red-600 rounded transition-colors shrink-0"
                  title="删除">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

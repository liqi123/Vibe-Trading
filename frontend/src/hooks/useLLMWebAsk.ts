/**
 * 网页 LLM（豆包 / DeepSeek / Kimi）问询封装。
 *
 * 统一「提交异步任务 + 轮询进度 + 取回答」，供多个页面复用：
 *   - POST /tools/llm-web/ask       提交任务（返回 {ok, job_id}）
 *   - GET  /tools/llm-web/progress/{job_id}  轮询直到 done
 *
 * 各页面只需组装 body 并处理结果，不再各自复制轮询样板。
 */

import { useCallback } from "react";
import { api } from "@/lib/api";

export interface LLMAskBody {
  target: string;
  /** 传 prompt 用给定文本；用集合竞价模板则传 use_template=true（+ 可选 stage/date）。 */
  prompt?: string;
  use_template?: boolean;
  use_file?: boolean;
  stage?: number;
  date?: string;
  timeout_s?: number;
}

export interface LLMAskResult {
  target: string;
  answer: string;
  elapsed_s?: number | null;
  logs: string[];
  /** 失败时非空；成功则无该字段。 */
  error?: string;
}

export interface LLMAskOptions {
  pollMs?: number;
  /** 每次轮询拿到日志时回调（用于前端实时展示进度）。 */
  onLogs?: (target: string, logs: string[]) => void;
  /**
   * 前端整体兜底超时（毫秒）。默认按 body.timeout_s + 60s 余量；
   * 任务在后端卡死 / 被裁剪但接口异常时，避免前端无限轮询。
   */
  deadlineMs?: number;
  /** 允许的连续轮询请求失败次数（瞬时网络抖动容错），默认 3。 */
  maxPollErrors?: number;
}

interface LLMAskStart {
  ok: boolean;
  job_id?: string;
  detail?: string;
}

interface LLMWebProgress {
  ok: boolean;
  done: boolean;
  success: boolean | null;
  answer: string;
  detail: string;
  logs: string[];
  elapsed_s?: number | null;
  target: string;
}

const DEFAULT_POLL_MS = 1300;
/** 未传 timeout_s 时的整体兜底超时（默认按后端 180s + 60s 余量）。 */
const DEFAULT_DEADLINE_MS = 240_000;

export function useLLMWebAsk() {
  const askOne = useCallback(
    async (body: LLMAskBody, opts?: LLMAskOptions): Promise<LLMAskResult> => {
      const pollMs = opts?.pollMs ?? DEFAULT_POLL_MS;
      const deadlineMs =
        opts?.deadlineMs ?? (body.timeout_s ? body.timeout_s * 1000 + 60_000 : DEFAULT_DEADLINE_MS);
      const maxPollErrors = opts?.maxPollErrors ?? 3;
      const start = await api.tools.post<LLMAskStart>("/llm-web/ask", body);
      if (!start?.ok || !start.job_id) {
        throw new Error(start?.detail || "任务提交失败");
      }
      const deadline = Date.now() + deadlineMs;
      let pollErrors = 0;
      for (;;) {
        if (Date.now() > deadline) {
          throw new Error(`等待超时（>${Math.round(deadlineMs / 1000)}s）：任务未在期限内完成`);
        }
        await new Promise((r) => setTimeout(r, pollMs));
        let p: LLMWebProgress | null;
        try {
          p = await api.tools.get<LLMWebProgress>(`/llm-web/progress/${start.job_id}`);
          pollErrors = 0;
        } catch (e: any) {
          pollErrors += 1;
          if (pollErrors > maxPollErrors) {
            throw new Error(`轮询进度接口连续失败 ${pollErrors} 次：${String(e?.message ?? e)}`);
          }
          continue;
        }
        if (p?.ok === false) {
          // 后端明确报错（如任务被裁剪：「任务不存在或已过期」）
          throw new Error(p.detail || "任务不存在或已过期");
        }
        if (p?.logs?.length && opts?.onLogs) opts.onLogs(body.target, p.logs);
        if (p?.done) {
          if (p.success) {
            return { target: body.target, answer: p.answer || "", elapsed_s: p.elapsed_s, logs: p.logs || [] };
          }
          throw new Error(p.detail || "自动化失败");
        }
      }
    },
    [],
  );

  /** 并发问多路；各自独立成败，不因某一路失败中断其他路。 */
  const askMany = useCallback(
    async (
      items: Array<LLMAskBody & { label?: string }>,
      opts?: LLMAskOptions & { onDone?: (r: LLMAskResult) => void },
    ): Promise<LLMAskResult[]> => {
      const results = await Promise.all(
        items.map(async (body) => {
          try {
            const r = await askOne(body, {
              pollMs: opts?.pollMs,
              onLogs: opts?.onLogs ? (t, l) => opts.onLogs?.(t, l) : undefined,
            });
            opts?.onDone?.(r);
            return r;
          } catch (e: any) {
            const bad: LLMAskResult = {
              target: body.target,
              answer: "",
              elapsed_s: null,
              logs: [],
              error: String(e?.message ?? e),
            };
            opts?.onDone?.(bad);
            return bad;
          }
        }),
      );
      return results;
    },
    [askOne],
  );

  return { askOne, askMany };
}

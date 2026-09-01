import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLLMWebAsk } from "../useLLMWebAsk";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    tools: {
      post: vi.fn(),
      get: vi.fn(),
    },
  },
}));

const mockPost = vi.mocked(api.tools.post);
const mockGet = vi.mocked(api.tools.get);

beforeEach(() => {
  vi.useFakeTimers();
  mockPost.mockReset();
  mockGet.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

/** 运行回调并推进 fake timers，直到异步完成（poll 循环依赖 setTimeout）。 */
async function runAsync<T>(fn: () => Promise<T>): Promise<T> {
  const promise = fn();
  // 预挂 no-op 用于吞掉推进 timers 期间可能先抛出的 rejection，避免 Vitest 误报 unhandled。
  // 调用方仍用 .rejects/.resolves 对同一 promise 做断言。
  promise.catch(() => {});
  for (let i = 0; i < 200; i++) {
    await vi.advanceTimersByTimeAsync(2000);
  }
  return promise;
}

const probe = (done: boolean, success: boolean, over: Record<string, unknown> = {}) => ({
  ok: true,
  done,
  success,
  answer: "",
  detail: "",
  logs: [],
  target: "doubao",
  elapsed_s: null,
  ...over,
});

describe("useLLMWebAsk", () => {
  it("askOne polls until done and returns answer", async () => {
    mockPost.mockResolvedValue({ ok: true, job_id: "abc" });
    mockGet
      .mockResolvedValueOnce(probe(false, null, { logs: ["start"] }))
      .mockResolvedValueOnce(probe(true, true, { answer: "好", elapsed_s: 3, logs: ["done"] }));

    const { result } = renderHook(() => useLLMWebAsk());
    const res = await runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }));
    expect(res.answer).toBe("好");
    expect(res.elapsed_s).toBe(3);
    expect(res.target).toBe("doubao");
  });

  it("askOne reports progress via onLogs", async () => {
    mockPost.mockResolvedValue({ ok: true, job_id: "abc" });
    mockGet
      .mockResolvedValueOnce(probe(false, null, { logs: ["start"] }))
      .mockResolvedValueOnce(probe(true, true, { answer: "好", elapsed_s: 2, logs: ["done"] }));

    const onLogs = vi.fn();
    const { result } = renderHook(() => useLLMWebAsk());
    await runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }, { onLogs }));
    expect(onLogs).toHaveBeenCalledWith("doubao", ["start"]);
  });

  it("askOne throws when task fails", async () => {
    mockPost.mockResolvedValue({ ok: true, job_id: "abc" });
    mockGet.mockResolvedValue(probe(true, false, { detail: "登录态失效" }));

    const { result } = renderHook(() => useLLMWebAsk());
    const promise = runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }));
    await expect(promise).rejects.toThrow("登录态失效");
  });

  it("askOne throws when submission fails", async () => {
    mockPost.mockResolvedValue({ ok: false, detail: "未知目标" });
    const { result } = renderHook(() => useLLMWebAsk());
    await expect(result.current.askOne({ target: "nope", prompt: "hi" })).rejects.toThrow("未知目标");
  });

  it("askOne stops immediately when backend says job missing (ok:false)", async () => {
    // 后端 _JOBS_MAX 裁剪旧任务时返回 {ok:false, detail:任务不存在…}，无 done 字段
    mockPost.mockResolvedValue({ ok: true, job_id: "gone" });
    mockGet.mockResolvedValue({
      ok: false,
      done: false,
      success: null,
      answer: "",
      detail: "任务不存在或已过期: gone",
      logs: [],
      target: "doubao",
    });

    const { result } = renderHook(() => useLLMWebAsk());
    const promise = runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }));
    await expect(promise).rejects.toThrow("任务不存在或已过期");
    // 不应无限轮询：进度接口只被调一次
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("askOne aborts on overall deadline instead of polling forever", async () => {
    mockPost.mockResolvedValue({ ok: true, job_id: "stuck" });
    // 任务永远不 done（后端卡死场景）
    mockGet.mockResolvedValue(probe(false, null));

    const { result } = renderHook(() => useLLMWebAsk());
    const promise = runAsync(() =>
      result.current.askOne({ target: "doubao", prompt: "hi" }, { deadlineMs: 1000 }),
    );
    await expect(promise).rejects.toThrow("等待超时");
  });

  it("askOne tolerates transient poll errors but fails after max consecutive errors", async () => {
    mockPost.mockResolvedValue({ ok: true, job_id: "flaky" });
    // 连续 3 次网络抖动（默认容错上限 3）后恢复正常并成功
    mockGet
      .mockRejectedValueOnce(new Error("network glitch 1"))
      .mockRejectedValueOnce(new Error("network glitch 2"))
      .mockRejectedValueOnce(new Error("network glitch 3"))
      .mockResolvedValueOnce(probe(true, true, { answer: "恢复了" }));

    const { result } = renderHook(() => useLLMWebAsk());
    const res = await runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }));
    expect(res.answer).toBe("恢复了");

    // 超过容错上限：连续 4 次失败应报错
    mockPost.mockResolvedValue({ ok: true, job_id: "dead" });
    mockGet.mockReset();
    mockGet.mockRejectedValue(new Error("connection refused"));
    const promise2 = runAsync(() => result.current.askOne({ target: "doubao", prompt: "hi" }));
    await expect(promise2).rejects.toThrow("连续失败 4 次");
  });

  it("askMany settles each route independently", async () => {
    mockPost
      .mockResolvedValueOnce({ ok: true, job_id: "a" })
      .mockResolvedValueOnce({ ok: true, job_id: "b" });
    mockGet
      .mockResolvedValueOnce(probe(true, true, { answer: "A答" }))
      .mockResolvedValueOnce(probe(true, false, { detail: "失败", target: "deepseek" }));

    const { result } = renderHook(() => useLLMWebAsk());
    const res = await runAsync(() =>
      result.current.askMany([
        { target: "doubao", label: "豆包", prompt: "hi" },
        { target: "deepseek", label: "DeepSeek", prompt: "hi" },
      ]),
    );
    expect(res).toHaveLength(2);
    expect(res[0].answer).toBe("A答");
    expect(res[0].error).toBeUndefined();
    expect(res[1].target).toBe("deepseek");
    expect(res[1].error).toBe("失败");
  });
});

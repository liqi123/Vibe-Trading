import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  describeConnAge,
  describeReload,
  describeSilence,
  installReloadProbe,
  readSnapshot,
} from "../reloadProbe";

describe("reloadProbe", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  describe("describeReload", () => {
    it("判定 HMR WebSocket 断开触发的强制刷新", () => {
      const verdict = describeReload(
        { viteLogs: ["[vite] server connection lost. Polling for restart..."] },
        "reload",
      );
      expect(verdict).toContain("HMR WebSocket 断开");
    });

    it("捕获到其它 vite 日志时原样给出", () => {
      expect(describeReload({ viteLogs: ["[vite] hmr update /src/x.ts"] }, "reload")).toContain(
        "hmr update",
      );
    });

    it("无 vite 日志时按 navigation type 判定", () => {
      expect(describeReload({ viteLogs: [] }, "reload")).toContain("page reload");
      expect(describeReload({ viteLogs: [] }, "back_forward")).toContain("标签页被丢弃");
      expect(describeReload({ viteLogs: [] }, "navigate")).toContain("证据不足");
    });
  });

  describe("describeSilence", () => {
    const t0 = 1_000_000;
    const alive = { at: t0, unloadAt: null, visibility: "visible" };

    it("心跳新鲜且未卸载 → 前台运行中被外部掐断", () => {
      expect(describeSilence(alive, t0 + 5_000)).toContain("前台运行中被外部掐断");
    });

    it("心跳新鲜但 pagehide 已触发 → 正常卸载流程", () => {
      expect(describeSilence({ ...alive, unloadAt: t0 + 1_000 }, t0 + 5_000)).toContain(
        "正常卸载流程",
      );
    });

    it("心跳新鲜但停在 hidden → 页面在后台时连接断开", () => {
      expect(describeSilence({ ...alive, visibility: "hidden" }, t0 + 5_000)).toContain(
        "后台时连接断开",
      );
    });

    it("心跳停摆超过阈值 → 页面被后台节流/丢弃", () => {
      const stale = { at: t0, unloadAt: null, visibility: "hidden" };
      expect(describeSilence(stale, t0 + 120_000)).toContain("后台被节流/丢弃");
      expect(describeSilence({ ...stale, visibility: "visible" }, t0 + 120_000)).toContain(
        "标签页丢弃",
      );
    });
  });

  describe("describeConnAge", () => {
    it("命中已知超时窗口时提示固定超时", () => {
      expect(describeConnAge(1_000_000, 1_000_000 + 300_000)).toContain("固定超时");
      expect(describeConnAge(1_000_000, 1_000_000 + 60_000)).toContain("固定超时");
    });

    it("不在已知窗口内时判为随机外部事件", () => {
      expect(describeConnAge(1_000_000, 1_000_000 + 47_000)).toContain("随机外部事件");
      expect(describeConnAge(1_000_000, 1_000_000 + 1_000)).toContain("随机外部事件");
    });
  });

  it("跨加载保存 vite 断线日志，并在下次加载时上报判定", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    const fetchSpy = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("fetch", fetchSpy);

    // 第一次加载：建立快照，无历史故不上报
    installReloadProbe();
    expect(readSnapshot()?.viteLogs).toEqual([]);
    expect(warn).not.toHaveBeenCalled();

    // 模拟 vite client 在 location.reload() 之前打印的断线日志
    console.log("[vite] server connection lost. Polling for restart...");
    expect(readSnapshot()?.viteLogs).toHaveLength(1);

    // 第二次加载（= 整页刷新之后）：读回现场并上报
    installReloadProbe();
    expect(warn).toHaveBeenCalledTimes(1);
    const reported = String(warn.mock.calls[0]?.[0]);
    expect(reported).toContain("[reload-probe]");
    expect(reported).toContain("HMR WebSocket 断开");

    // 取证同步 POST 给 dev server，避免控制台被刷新清掉
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/__reload_probe");
    const body = JSON.parse(String(init?.body));
    expect(body.verdict).toContain("HMR WebSocket 断开");
    expect(body.viteLogs).toHaveLength(1);
    expect(body.connAgeMs).toBeGreaterThanOrEqual(0);
    expect(body.connAge).toContain("连接存活");

    // 上报后现场被重置，不会把同一条证据报第二遍
    expect(readSnapshot()?.viteLogs).toEqual([]);
    installReloadProbe();
    expect(warn).toHaveBeenCalledTimes(2);
    expect(String(warn.mock.calls[1]?.[0])).not.toContain("HMR WebSocket 断开");
  });

  it("sessionStorage 损坏或被禁用时静默降级", () => {
    sessionStorage.setItem("qa_reload_probe:v1", "{not json");
    expect(readSnapshot()).toBeNull();
    expect(() => installReloadProbe()).not.toThrow();
    expect(readSnapshot()?.at).toBeTypeOf("number");
  });

  it("pagehide 只记 unloadAt，不刷新心跳（否则静默时长会被掩盖）", () => {
    installReloadProbe();
    const before = readSnapshot()!;
    expect(before.unloadAt).toBeNull();

    vi.advanceTimersByTime(3_000);
    window.dispatchEvent(new Event("pagehide"));

    const after = readSnapshot()!;
    expect(after.at).toBe(before.at); // 心跳未被 unload 推进
    expect(after.unloadAt).toBe(before.at + 3_000);
  });

  it("visibilitychange 写入时间线并更新可见性", () => {
    installReloadProbe();
    expect(readSnapshot()?.timeline).toEqual([]);

    vi.advanceTimersByTime(2_000);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    const snap = readSnapshot()!;
    expect(snap.visibility).toBe("hidden");
    expect(snap.timeline.join()).toContain("visibility=hidden");

    // 状态未变时不再重复追加
    document.dispatchEvent(new Event("visibilitychange"));
    expect(readSnapshot()?.timeline).toHaveLength(1);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });
});

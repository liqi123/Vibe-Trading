/**
 * Reload probe — 页面“自动刷新”的自动取证。
 *
 * 整页刷新会清空页面内存，所以现场证据都写进 sessionStorage 跨加载存活：
 *   1. 上一次加载的 navigation type + 心跳 → 是否真 reload、页面死前静默了多久
 *   2. 刷新前捕获的 vite 控制台日志 → 是不是 HMR WebSocket 断开触发的强制 reload
 *   3. 时间线（可见性切换 / vite 日志）+ pagehide 时间 → 区分前台断开、后台节流、标签页被丢弃
 *
 * 注意：心跳只走 setInterval，不写 pagehide —— 否则 unload 会把 `at` 刷成最新，
 * 静默时长恒等于“reload→load 延迟”，看不出页面死前是否早已失去心跳。
 *
 * 服务端（Vite stdout）对 HMR ws 断开这条路径是零日志的，因此只能在客户端取证。
 *
 * 安装：`main.tsx` 调用一次 `installReloadProbe()`。
 * 复盘：F12 Console 过滤 `[reload-probe]`；取证文件 scripts/_reload_probe.log。
 */

const STORE_KEY = "qa_reload_probe:v1";
const HEARTBEAT_MS = 5_000;
const RECENT_WINDOW_MS = 10 * 60_000;
const MAX_VITE_LOGS = 10;
const MAX_TIMELINE = 24;
/** 心跳超过这个间隔没来，说明页面已被后台节流或丢弃 */
const STALE_HEARTBEAT_MS = 20_000;

/** vite client 会打这些前缀/文案；命中即视为“刷新前的现场证据” */
const VITE_PATTERN = /\[vite\]|server connection lost|page reload|full-reload/i;
/** 本探针自己的输出，必须跳过，否则会把自己的报告当成现场证据 */
const SELF_PATTERN = /\[reload-probe\]/;
/** vite client 在 ws 断开后轮询 ping、成功即 reload 的那条日志 */
const HMR_DISCONNECT_PATTERN = /server connection lost/i;

const CONSOLE_LEVELS = ["log", "info", "warn", "error"] as const;
type ConsoleLevel = (typeof CONSOLE_LEVELS)[number];
type ProbeFn = ((...args: unknown[]) => void) & { __reloadProbePristine?: ProbeFn };

export interface Snapshot {
  /** 最后一次 interval 心跳（ms epoch）；不被 pagehide 覆盖 */
  at: number;
  /** 页面导航开始时刻（performance.timeOrigin），据此算 HMR 连接存活时长 */
  loadedAt: number;
  /** pagehide/beforeunload 时间；null = 没走到正常卸载 */
  unloadAt: number | null;
  href: string;
  /** navigate | reload | back_forward | prerender | unknown */
  navType: string;
  /** 最后一次心跳时的 visibilityState */
  visibility: string;
  /** 时间线：可见性切换 + vite 日志，每条 `HH:MM:SS <事件>` */
  timeline: string[];
  /** 刷新前捕获到的 vite 日志 */
  viteLogs: string[];
  /** 本标签页最近 RECENT_WINDOW_MS 内每次加载的时间戳 */
  loads: number[];
}

export function readSnapshot(): Snapshot | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(STORE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<Snapshot>;
    if (typeof parsed?.at !== "number") return null;
    return {
      at: parsed.at,
      loadedAt: typeof parsed.loadedAt === "number" ? parsed.loadedAt : parsed.at,
      unloadAt: typeof parsed.unloadAt === "number" ? parsed.unloadAt : null,
      href: parsed.href ?? "",
      navType: parsed.navType ?? "unknown",
      visibility: parsed.visibility ?? "unknown",
      timeline: Array.isArray(parsed.timeline) ? parsed.timeline : [],
      viteLogs: Array.isArray(parsed.viteLogs) ? parsed.viteLogs : [],
      loads: Array.isArray(parsed.loads) ? parsed.loads : [],
    };
  } catch {
    return null;
  }
}

function writeSnapshot(snapshot: Snapshot): void {
  try {
    window.sessionStorage.setItem(STORE_KEY, JSON.stringify(snapshot));
  } catch {
    /* sessionStorage 不可用时静默降级 */
  }
}

function stamp(at: number): string {
  const d = new Date(at);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/**
 * 判定上一次加载为何结束。纯函数，便于单测。
 */
export function describeReload(previous: Pick<Snapshot, "viteLogs">, navType: string): string {
  if (previous.viteLogs.some((line) => HMR_DISCONNECT_PATTERN.test(line))) {
    return "Vite HMR WebSocket 断开 → client 强制 location.reload()";
  }
  if (previous.viteLogs.length) {
    return `捕获到 vite 日志（无 server connection lost）: ${previous.viteLogs.join(" | ")}`;
  }
  if (navType === "reload") {
    return (
      "type=reload 且客户端无 vite 日志 → 与 _frontend_out.log 的 " +
      "'[vite] page reload' 时间戳对账：有=改文件触发，无=浏览器侧（标签页被丢弃后恢复/手动F5）"
    );
  }
  if (navType === "back_forward") {
    return "type=back_forward → 会话历史恢复（标签页被丢弃后恢复的典型表现）";
  }
  return `type=${navType} 且无 vite 日志 → 证据不足，看时间线`;
}

/**
 * 断开时页面活着没有。纯函数，便于单测。
 * - 心跳新鲜 + 前台 → 连接在正常运行中被外部掐断
 * - 心跳陈旧 → 页面已被后台节流/丢弃，reload 发生在恢复时
 */
export function describeSilence(previous: Pick<Snapshot, "at" | "unloadAt" | "visibility">, now: number): string {
  const silentFor = Math.max(0, now - previous.at);
  if (silentFor > STALE_HEARTBEAT_MS) {
    return previous.visibility === "hidden"
      ? `心跳已停 ${(silentFor / 1000).toFixed(0)}s 且最后状态 hidden → 页面在后台被节流/丢弃，恢复时触发 reload`
      : `心跳已停 ${(silentFor / 1000).toFixed(0)}s → 页面很可能已被标签页丢弃`;
  }
  if (previous.visibility === "hidden") {
    return `心跳新鲜但最后状态 hidden → 页面在后台时连接断开`;
  }
  return previous.unloadAt !== null
    ? "心跳新鲜、pagehide 已触发 → 正常卸载流程"
    : "心跳新鲜且未走 pagehide → 连接在前台运行中被外部掐断";
}

/** Node/Vite 常见连接超时（ms），连接年龄落在这附近即高度可疑 */
const KNOWN_TIMEOUTS_MS = [5_000, 60_000, 180_000, 300_000, 3_600_000];

/**
 * HMR 连接年龄判定。纯函数，便于单测。
 * 页面导航开始≈ws 建立（@vite/client 在模块求值时就连），故可用 loadedAt 近似。
 */
export function describeConnAge(loadedAt: number, now: number): string {
  const age = Math.max(0, now - loadedAt);
  const hit = KNOWN_TIMEOUTS_MS.find((t) => Math.abs(age - t) <= 2_000);
  return hit
    ? `连接存活 ${(age / 1000).toFixed(0)}s ≈ ${hit / 1000}s → 高度疑似固定超时被掐断`
    : `连接存活 ${(age / 1000).toFixed(0)}s → 非固定超时，属随机外部事件`;
}

function getNavigationType(): string {
  try {
    const entries = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
    return entries[0]?.type || "unknown";
  } catch {
    return "unknown";
  }
}

function formatArgs(args: unknown[]): string {
  return args
    .map((arg) => {
      if (typeof arg === "string") return arg;
      try {
        return JSON.stringify(arg) ?? String(arg);
      } catch {
        return String(arg);
      }
    })
    .join(" ");
}

/**
 * 包装 console，捕获 vite 日志。重复安装时始终转发给最初的原始实现，
 * 不会形成嵌套调用链。
 */
function tapConsole(onLine: (line: string) => void): void {
  for (const level of CONSOLE_LEVELS) {
    const current = console[level] as ProbeFn;
    const pristine = (current.__reloadProbePristine ?? current) as ProbeFn;
    const wrapper: ProbeFn = (...args: unknown[]) => {
      const line = formatArgs(args);
      if (SELF_PATTERN.test(line)) {
        // 自己的报告，直接透传，不当现场证据
      } else if (VITE_PATTERN.test(line)) {
        onLine(line);
      }
      pristine(...args);
    };
    wrapper.__reloadProbePristine = pristine;
    (console as unknown as Record<ConsoleLevel, ProbeFn>)[level] = wrapper;
  }
}

function appendViteLog(line: string): void {
  const snapshot = readSnapshot();
  if (!snapshot) return;
  const now = Date.now();
  writeSnapshot({
    ...snapshot,
    viteLogs: [...snapshot.viteLogs, line].slice(-MAX_VITE_LOGS),
    timeline: [...snapshot.timeline, `${stamp(now)} vite: ${line}`].slice(-MAX_TIMELINE),
  });
}

/** 只更新心跳与可见性，绝不写 unloadAt —— 见文件头注释 */
function touchHeartbeat(): void {
  const snapshot = readSnapshot();
  if (!snapshot) return;
  writeSnapshot({ ...snapshot, at: Date.now(), visibility: document.visibilityState });
}

function handleVisibilityChange(): void {
  const snapshot = readSnapshot();
  if (!snapshot) return;
  const state = document.visibilityState;
  if (state === snapshot.visibility) return;
  writeSnapshot({
    ...snapshot,
    visibility: state,
    timeline: [...snapshot.timeline, `${stamp(Date.now())} visibility=${state}`].slice(-MAX_TIMELINE),
  });
}

function handleUnload(): void {
  const snapshot = readSnapshot();
  if (!snapshot || snapshot.unloadAt !== null) return;
  writeSnapshot({ ...snapshot, unloadAt: Date.now() });
}

interface ReloadReport {
  /** 上报时间 */
  reportedAt: number;
  /** 本次加载的 navigation type */
  navType: string;
  href: string;
  previousHref: string;
  /** 上次心跳距今（ms）——只由 interval 维护，不被 pagehide 掩盖 */
  silentForMs: number;
  /** 上次页面存活时长（ms）——HMR 连接大致年龄；固定值=服务端超时，随机值=外部事件 */
  connAgeMs: number;
  /** 连接年龄的人读判定 */
  connAge: string;
  /** 上次心跳时的 visibilityState */
  prevVisibility: string;
  /** 上次 pagehide 时间；null = 没走到正常卸载 */
  prevUnloadAt: number | null;
  /** 近 10 分钟加载次数 */
  recentLoads: number;
  /** 刷新前捕获的 vite 日志 */
  viteLogs: string[];
  /** 上次加载期的可见性/日志时间线 */
  timeline: string[];
  verdict: string;
  silence: string;
}

/**
 * 取证结果上报到 dev server（vite.config.ts 的 reloadProbeSink），
 * 落成 scripts/_reload_probe.log —— 控制台会被刷新清掉，文件不会。
 */
function sendReport(report: ReloadReport): void {
  try {
    void fetch("/__reload_probe", {
      method: "POST",
      body: JSON.stringify(report),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* 生产构建没有该端点，静默降级 */
  }
}

function logReload(previous: Snapshot, navType: string, now: number): void {
  const silentFor = Math.max(0, now - previous.at);
  const connAgeMs = Math.max(0, now - previous.loadedAt);
  const recentLoads = [...previous.loads, now].filter((t) => now - t <= RECENT_WINDOW_MS).length;
  const verdict = describeReload(previous, navType);
  const silence = describeSilence(previous, now);
  const connAge = describeConnAge(previous.loadedAt, now);
  const report: ReloadReport = {
    reportedAt: now,
    navType,
    href: location.href,
    previousHref: previous.href,
    silentForMs: silentFor,
    connAgeMs,
    connAge,
    prevVisibility: previous.visibility,
    prevUnloadAt: previous.unloadAt,
    recentLoads,
    viteLogs: previous.viteLogs,
    timeline: previous.timeline,
    verdict,
    silence,
  };
  console.warn(
    `%c[reload-probe] 检测到页面重新加载\n` +
      `  判定: ${verdict}\n` +
      `  存活: ${silence}\n` +
      `  连接: ${connAge}\n` +
      `  navigation type: ${navType}\n` +
      `  上次URL: ${previous.href}\n` +
      `  心跳距今: ${(silentFor / 1000).toFixed(1)}s / visibility=${previous.visibility}\n` +
      `  近10分钟加载: ${recentLoads} 次\n` +
      `  时间线: ${previous.timeline.length ? previous.timeline.join(" → ") : "(无)"}\n` +
      `  刷新前 vite 日志: ${previous.viteLogs.length ? previous.viteLogs.join(" | ") : "(无)"}`,
    "color:#f59e0b;font-weight:bold",
  );
  sendReport(report);
}

let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let unloadBound = false;
let visibilityBound = false;

export function installReloadProbe(): void {
  const now = Date.now();
  const navType = getNavigationType();
  const previous = readSnapshot();

  if (previous) logReload(previous, navType, now);

  const loadedAt = Math.round(performance.timeOrigin || now - performance.now());
  writeSnapshot({
    at: now,
    loadedAt,
    unloadAt: null,
    href: location.href,
    navType,
    visibility: document.visibilityState,
    timeline: [],
    viteLogs: [],
    loads: previous ? [...previous.loads, now].filter((t) => now - t <= RECENT_WINDOW_MS) : [now],
  });

  tapConsole(appendViteLog);

  if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer);
  heartbeatTimer = window.setInterval(touchHeartbeat, HEARTBEAT_MS);
  if (!unloadBound) {
    unloadBound = true;
    window.addEventListener("pagehide", handleUnload);
    window.addEventListener("beforeunload", handleUnload);
  }
  if (!visibilityBound) {
    visibilityBound = true;
    document.addEventListener("visibilitychange", handleVisibilityChange);
  }
}

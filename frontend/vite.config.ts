import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "path";

const PROXY_PATHS = [
  "/sessions",
  "/swarm/presets",
  "/swarm/runs",
  "/qveris",
  "/settings/llm",
  "/settings/data-sources",
  "/channels",
  "/mandate",
  "/live",
  "/upload",
  "/shadow-reports",
  "/tools",
];

// [reload-probe] 客户端把"页面为何重新加载"的取证 POST 回来，落成日志供离线分析。
// 日志写在 frontend 根目录之外：写在根目录里会一直被 chokidar 监听到。
const RELOAD_PROBE_LOG = path.resolve(__dirname, "../../scripts/_reload_probe.log");

function reloadProbeSink(): Plugin {
  return {
    name: "reload-probe-sink",
    configureServer(server) {
      server.middlewares.use("/__reload_probe", (req, res) => {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.end();
          return;
        }
        const chunks: Buffer[] = [];
        req.on("data", (chunk: Buffer) => chunks.push(chunk));
        req.on("end", () => {
          try {
            const line = `${new Date().toISOString()} ${Buffer.concat(chunks).toString("utf8")}\n`;
            fs.appendFileSync(RELOAD_PROBE_LOG, line);
          } catch {
            // 诊断通道自身出错绝不能影响页面
          }
          res.statusCode = 204;
          res.end();
        });
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_URL || "http://127.0.0.1:8899";
  // proxy 超时 5 分钟，避免长耗时请求（如 czsc/scan 全市场扫描）被截断
  const apiProxy = { target: apiTarget, changeOrigin: true, timeout: 300000 };
  const apiProxyWithHtmlFallback = {
    ...apiProxy,
    bypass(req: { headers: { accept?: string } }) {
      if (req.headers.accept?.includes("text/html")) {
        return "/index.html";
      }
    },
  };

  return {
    plugins: [react(), reloadProbeSink()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      host: true,
      port: 5899,
      proxy: {
        ...Object.fromEntries(PROXY_PATHS.map((p) => [p, apiProxy])),
        // SPA RunDetail page — only the two-segment ``/runs/{id}``
        // form should fall back to ``index.html`` on browser navigation.
        // ``/runs/{id}/code`` and ``/runs/{id}/pine`` are API-only and
        // must keep proxying to the backend even when Accept is text/html.
        "^/runs/[^/]+/?$": apiProxyWithHtmlFallback,
        "/runs": apiProxy,
        "/correlation": apiProxyWithHtmlFallback,
        "^/alpha(?:/|$)": apiProxy,
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            "vendor-react": ["react", "react-dom", "react-router-dom"],
            "vendor-charts": ["echarts"],
          },
        },
      },
    },
  };
});

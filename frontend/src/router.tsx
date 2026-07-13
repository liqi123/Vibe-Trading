import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";

const Home = lazy(() => import("@/pages/Home").then((m) => ({ default: m.Home })));
const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Runtime = lazy(() =>
  import("@/pages/Runtime").then((m) => ({ default: m.Runtime })),
);
const Reports = lazy(() =>
  import("@/pages/Reports").then((m) => ({ default: m.Reports })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);
const AlphaZoo = lazy(() =>
  import("@/pages/AlphaZoo").then((m) => ({ default: m.AlphaZoo })),
);
const PaperTrading = lazy(() =>
  import("@/pages/PaperTrading").then((m) => ({ default: m.PaperTrading })),
);
const DailyScan = lazy(() =>
  import("@/pages/DailyScan").then((m) => ({ default: m.DailyScan })),
);
const Tools = lazy(() =>
  import("@/pages/Tools").then((m) => ({ default: m.Tools })),
);
const Watchlist = lazy(() =>
  import("@/pages/Watchlist").then((m) => ({ default: m.Watchlist })),
);
const Overview = lazy(() =>
  import("@/pages/Overview").then((m) => ({ default: m.Overview })),
);
const CalcTools = lazy(() =>
  import("@/pages/CalcTools").then((m) => ({ default: m.CalcTools })),
);
const TradeJournal = lazy(() =>
  import("@/pages/tools/TradeJournal").then((m) => ({ default: m.TradeJournal })),
);
const AIAnalysis = lazy(() =>
  import("@/pages/tools/AIAnalysis").then((m) => ({ default: m.AIAnalysis })),
);
const BacktestEval = lazy(() =>
  import("@/pages/tools/BacktestEval").then((m) => ({ default: m.BacktestEval })),
);
const NewsSearch = lazy(() =>
  import("@/pages/tools/NewsSearch").then((m) => ({ default: m.NewsSearch })),
);
const DailyReview = lazy(() =>
  import("@/pages/tools/DailyReview").then((m) => ({ default: m.DailyReview })),
);
const ScheduledTasks = lazy(() =>
  import("@/pages/ScheduledTasks").then((m) => ({ default: m.ScheduledTasks })),
);
const AuctionBoard = lazy(() =>
  import("@/pages/AuctionBoard").then((m) => ({ default: m.AuctionBoard })),
);
const StockAnalysis = lazy(() =>
  import("@/pages/tools/StockAnalysis").then((m) => ({ default: m.StockAnalysis })),
);
const MarketLadder = lazy(() =>
  import("@/pages/MarketLadder").then((m) => ({ default: m.MarketLadder })),
);
const VolumeRank = lazy(() =>
  import("@/pages/VolumeRank").then((m) => ({ default: m.VolumeRank })),
);

function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: wrap(Home) },
      { path: "/agent", element: wrap(Agent) },
      { path: "/runtime", element: wrap(Runtime) },
      { path: "/reports", element: wrap(Reports) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
      { path: "/alpha-zoo", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/bench", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/compare", element: wrap(AlphaZoo) },
      { path: "/alpha-zoo/:alphaId", element: wrap(AlphaZoo) },
      { path: "/overview", element: wrap(Overview) },
      { path: "/tools", element: wrap(Tools) },
      { path: "/paper-trading", element: wrap(PaperTrading) },
      { path: "/daily-scan", element: wrap(DailyScan) },
      { path: "/watchlist", element: wrap(Watchlist) },
      { path: "/calc-tools", element: wrap(CalcTools) },
      { path: "/journal", element: wrap(TradeJournal) },
      { path: "/ai-analysis", element: wrap(AIAnalysis) },
      { path: "/backtest-eval", element: wrap(BacktestEval) },
      { path: "/news", element: wrap(NewsSearch) },
      { path: "/daily-review", element: wrap(DailyReview) },
      { path: "/scheduled-tasks", element: wrap(ScheduledTasks) },
      { path: "/auction-board", element: wrap(AuctionBoard) },
      { path: "/stock-analysis", element: wrap(StockAnalysis) },
      { path: "/market-ladder", element: wrap(MarketLadder) },
      { path: "/volume-rank", element: wrap(VolumeRank) },
    ],
  },
]);

import { Link } from "react-router-dom";
import { Target, Wallet, Search, Star, Calculator, BookOpen, Brain, TrendingUp, Newspaper } from "lucide-react";

const TOOLS = [
  {
    to: "/expectations",
    icon: Target,
    title: "预期管理",
    desc: "买入时记录预期（竞价量能、开盘方向、目标价），竞价后检查是否符合预期",
    color: "text-blue-500",
  },
  {
    to: "/paper-trading",
    icon: Wallet,
    title: "模拟盘",
    desc: "纸面交易持仓与收益跟踪，支持V1斐波那契和V5趋势策略",
    color: "text-green-500",
  },
  {
    to: "/daily-scan",
    icon: Search,
    title: "每日选股",
    desc: "策略扫描结果与市场概览，查看涨跌分布和市场宽度",
    color: "text-purple-500",
  },
  {
    to: "/watchlist",
    icon: Star,
    title: "自选股",
    desc: "自定义关注股票列表，实时查看价格和E/X/跑路价",
    color: "text-yellow-500",
  },
  {
    to: "/calc-tools",
    icon: Calculator,
    title: "计算工具",
    desc: "跑路价、出货价、斐波那契价位等实用计算",
    color: "text-orange-500",
  },
  {
    to: "/journal",
    icon: BookOpen,
    title: "交易日志",
    desc: "交易记录管理、盈亏统计、周度回顾报告",
    color: "text-teal-500",
  },
  {
    to: "/ai-analysis",
    icon: Brain,
    title: "AI 分析",
    desc: "LLM 驱动的个股分析，生成买卖建议报告",
    color: "text-purple-600",
  },
  {
    to: "/backtest-eval",
    icon: TrendingUp,
    title: "回测评估",
    desc: "评估选股后续N日收益表现，验证策略有效性",
    color: "text-red-500",
  },
  {
    to: "/news",
    icon: Newspaper,
    title: "新闻查询",
    desc: "多源新闻聚合，关键词搜索和个股新闻查询",
    color: "text-cyan-500",
  },
];

export function Tools() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">工具</h1>
        <p className="text-sm text-muted-foreground mt-1">选股策略、模拟盘、预期管理、分析工具</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {TOOLS.map(({ to, icon: Icon, title, desc, color }) => (
          <Link
            key={to}
            to={to}
            className="border rounded-lg p-6 bg-card hover:bg-muted/50 transition-colors group"
          >
            <Icon className={`h-10 w-10 ${color} mb-4 group-hover:scale-110 transition-transform`} />
            <h2 className="text-lg font-semibold mb-2">{title}</h2>
            <p className="text-sm text-muted-foreground">{desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

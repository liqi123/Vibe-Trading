import { Link } from "react-router-dom";
import { Wallet, Search, Star, Calculator, BookOpen, Brain, TrendingUp, Newspaper, BarChart3, LineChart, Layers, DollarSign, Gauge, Network, Crosshair, Eye } from "lucide-react";

const TOOLS = [
  {
    to: "/short-term-flow",
    icon: Crosshair,
    title: "短线全流程",
    desc: "盘前→竞价→盘中→持仓→盘后 贯穿一天：竞价情绪四阶段、持仓止盈止损企业微信告警、复盘闭环",
    color: "text-violet-500",
  },
  {
    to: "/tgb-signals",
    icon: Eye,
    title: "淘股吧信号监控",
    desc: "关注用户动态轮询，提取买卖/持有/计划信号与仓位限定词，空仓口径对账",
    color: "text-orange-500",
  },
  {
    to: "/auction-board",
    icon: BarChart3,
    title: "集合竞价看板",
    desc: "每日竞价量能排行、竞价对比、预期管理一站式监控",
    color: "text-violet-500",
  },
  {
    to: "/watchlist",
    icon: Star,
    title: "自选股",
    desc: "自定义关注股票列表，实时查看价格和E/X/跑路价",
    color: "text-yellow-500",
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
    to: "/market-ladder",
    icon: Layers,
    title: "连板梯队",
    desc: "涨停板高度与题材聚类，识别市场龙头与资金进攻方向",
    color: "text-red-500",
  },
  {
    to: "/calc-tools",
    icon: Calculator,
    title: "计算工具",
    desc: "跑路价、出货价、斐波那契价位等实用计算",
    color: "text-orange-500",
  },
  {
    to: "/volume-rank",
    icon: DollarSign,
    title: "成交额排行",
    desc: "全市场成交额TOP 50，按行业聚类分析主力资金流向",
    color: "text-blue-500",
  },
  {
    to: "/daily-review",
    icon: TrendingUp,
    title: "每日复盘",
    desc: "大盘/全球指数、市场情绪、连板梯队、成交额榜、板块资金一屏看全 + AI 复盘与本地复盘报告",
    color: "text-rose-500",
  },
  {
    to: "/vibe-review",
    icon: Brain,
    title: "短线智能体复盘",
    desc: "五智能体叙事复盘：情绪/资金/题材/龙虎榜/龙头 + 明日验证条件闭环 + 首板/外围/热度",
    color: "text-red-500",
  },
  {
    to: "/sentiment-index",
    icon: Gauge,
    title: "恐惧贪婪指数",
    desc: "增强版AFGI：9分项加权情绪温度计（波动率/成交/广度/涨跌停/赚钱效应等），五档状态",
    color: "text-indigo-500",
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
    to: "/stock-analysis",
    icon: LineChart,
    title: "个股深度分析",
    desc: "斐波那契价位、技术指标、摆动周期、K线数据一站式分析",
    color: "text-rose-500",
  },
  {
    to: "/czsc-analysis",
    icon: Network,
    title: "缠论结构分析",
    desc: "缠中说禅（czsc）分型/笔/中枢/三类买卖点识别 + 222信号函数选股扫描",
    color: "text-indigo-500",
  },
  {
    to: "/news",
    icon: Newspaper,
    title: "新闻查询",
    desc: "多源新闻聚合，关键词搜索和个股新闻查询",
    color: "text-cyan-500",
  },
  {
    to: "/journal",
    icon: BookOpen,
    title: "交易日志",
    desc: "交易记录管理、盈亏统计、周度回顾报告",
    color: "text-teal-500",
  },
];

export function Tools() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">工具</h1>
        <p className="text-sm text-muted-foreground mt-1">集合竞价、自选股、模拟盘、选股策略与分析工具</p>
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

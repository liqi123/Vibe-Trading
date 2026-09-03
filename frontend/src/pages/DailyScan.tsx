import { useEffect, useState, Fragment } from "react";
import { Search, RefreshCw, TrendingUp, Download, BarChart3, CandlestickChart as CandleIcon, X, Activity, Brain, Loader2 } from "lucide-react";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { SMCChart } from "@/components/charts/SMCChart";
import { api } from "@/lib/api";
import type { PriceBar } from "@/lib/api";
import { RunLogPanel } from "@/components/RunLogPanel";

interface MarketStats {
  total: number;
  up: number;
  down: number;
  flat: number;
  limit_up: number;
  limit_down: number;
}

interface Candidate {
  code: string;
  name: string;
  price: number;
  score: number;
  E?: number;
  deviation?: number;
  H?: number;
  L?: number;
  H_date?: string;
  L_date?: string;
  swing?: number;
  stop?: number;
  rsi?: number;
  adx?: number;
  trend?: number;
  momentum?: number;
  volume_s?: number;
  volatility?: number;
  liquidity?: number;
  rs?: number;
  turnover?: number;
  adx_s?: number;
  gtja_vp?: number;
  gtja_cp?: number;
  high52w?: number;
  strev?: number;
  retskew?: number;
  drawdown?: number;
  var_s?: number;
  regime?: number;
  adx_val?: number;
}

interface Column {
  key: string;
  label: string;
  align?: "left" | "right" | "center";
  render: (c: Candidate) => React.ReactNode;
}

function generateReasons(c: Candidate): string[] {
  const reasons: string[] = [];

  // ICT/SMC选股理由
  const ss = (c as any).structure_score ?? 0;
  const fvg = (c as any).fvg_score ?? 0;
  const ob = (c as any).ob_score ?? 0;
  const liq = (c as any).liquidity_score ?? 0;
  const ote = (c as any).ote_score ?? 0;
  const vol = (c as any).vol_score ?? 0;
  const s31 = (c as any).structure_3_1_score ?? 0;

  if (ss > 0 || fvg > 0 || ob > 0) {
    // 结构信号
    if (ss >= 15) {
      reasons.push('出现BOS结构突破，趋势延续确认');
    } else if (ss >= 10) {
      reasons.push('出现ChoCH角色转换，趋势反转信号');
    } else if (ss >= 5) {
      reasons.push('上升趋势中（HH/HL），方向明确');
    }

    // FVG
    if (fvg >= 25) {
      reasons.push('存在看涨FVG（公允价值缺口），机构足迹明显');
    } else if (fvg >= 10) {
      reasons.push('近期出现FVG信号，关注回补机会');
    }

    // 订单块
    if (ob >= 20) {
      reasons.push('价格在主要订单块（OB）区间内，机构吸筹区域');
    } else if (ob >= 15) {
      reasons.push('价格在次要订单块区间内，存在支撑');
    }

    // 流动性
    if (liq >= 10) {
      reasons.push('近期有流动性扫盘动作，主力清洗浮筹');
    } else if (liq >= 3) {
      reasons.push('接近流动性池区域，潜在支撑位');
    }

    // OTE
    if (ote >= 15) {
      reasons.push('价格处于OTE最优入场区（0.5-0.786斐波那契回撤）');
    } else if (ote >= 8) {
      reasons.push('价格接近OTE区域，合理回撤位');
    }

    // 成交量
    if (vol >= 10) {
      reasons.push('OB区域放量确认，资金介入明显');
    } else if (vol >= 5) {
      reasons.push('温和放量，关注度提升');
    }

    // 3-1结构
    if (s31 >= 5) {
      reasons.push('形成3-1结构（扫新低→更高低→突破），强力反转信号');
    }
  }

  // 斐波那契选股特有理由
  if (c.E !== undefined && c.deviation !== undefined) {
    if (c.deviation < 0.5) {
      reasons.push(`价格接近E价（偏差${c.deviation.toFixed(2)}%），处于关键支撑位`);
    } else if (c.deviation < 1) {
      reasons.push(`价格接近E价（偏差${c.deviation.toFixed(2)}%），接近支撑区域`);
    }
    if (c.swing !== undefined && c.swing > 20) {
      reasons.push(`摆动幅度${c.swing.toFixed(1)}%，波动空间较大`);
    }
  }

  // 趋势评分
  if (c.trend !== undefined) {
    if (c.trend >= 80) {
      reasons.push('趋势强劲，均线多头排列');
    } else if (c.trend >= 50) {
      reasons.push('趋势向好，价格在均线之上');
    } else if (c.trend >= 30) {
      reasons.push('趋势中性，价格在均线附近');
    } else {
      reasons.push('趋势较弱，价格在均线之下');
    }
  }

  // 动量评分
  if (c.momentum !== undefined) {
    if (c.momentum >= 80) {
      reasons.push('动量强劲，RSI处于健康区间');
    } else if (c.momentum >= 50) {
      reasons.push('动量适中，RSI表现正常');
    } else {
      reasons.push('动量较弱，RSI处于超卖或超买区域');
    }
  }

  // 成交量评分
  if (c.volume_s !== undefined) {
    if (c.volume_s >= 80) {
      reasons.push('成交量放大，资金关注度高');
    } else if (c.volume_s >= 50) {
      reasons.push('成交量适中，交投活跃');
    } else {
      reasons.push('成交量萎缩，市场关注度低');
    }
  }

  // 波动率评分
  if (c.volatility !== undefined) {
    if (c.volatility >= 80) {
      reasons.push('波动率适中，风险可控');
    } else if (c.volatility >= 50) {
      reasons.push('波动率正常，价格波动合理');
    } else {
      reasons.push('波动率异常，价格波动较大');
    }
  }

  // 流动性评分
  if (c.liquidity !== undefined) {
    if (c.liquidity >= 80) {
      reasons.push('流动性充足，便于进出');
    } else if (c.liquidity >= 50) {
      reasons.push('流动性良好，交易顺畅');
    } else {
      reasons.push('流动性不足，可能存在冲击成本');
    }
  }

  // 相对强度
  if (c.rs !== undefined) {
    if (c.rs >= 80) {
      reasons.push('相对强度高，跑赢大盘');
    } else if (c.rs >= 50) {
      reasons.push('相对强度适中，与大盘同步');
    } else {
      reasons.push('相对强度弱，跑输大盘');
    }
  }

  // ADX评分
  if (c.adx_s !== undefined) {
    if (c.adx_s >= 80) {
      reasons.push('ADX较高，趋势明确');
    } else if (c.adx_s >= 50) {
      reasons.push('ADX适中，趋势一般');
    } else {
      reasons.push('ADX较低，趋势不明朗');
    }
  }

  // 量价背离
  if (c.gtja_vp !== undefined) {
    if (c.gtja_vp >= 80) {
      reasons.push('量价配合良好，上涨有量能支撑');
    } else if (c.gtja_vp >= 50) {
      reasons.push('量价关系正常');
    } else {
      reasons.push('量价背离，需关注');
    }
  }

  // 收盘位置
  if (c.gtja_cp !== undefined) {
    if (c.gtja_cp >= 80) {
      reasons.push('收盘位置高，多头力量强');
    } else if (c.gtja_cp >= 50) {
      reasons.push('收盘位置适中');
    } else {
      reasons.push('收盘位置低，空头压力大');
    }
  }

  // 52周新高
  if (c.high52w !== undefined) {
    if (c.high52w >= 80) {
      reasons.push('接近52周新高，强势股特征');
    } else if (c.high52w >= 50) {
      reasons.push('处于52周中位区域');
    } else {
      reasons.push('距离52周高点较远');
    }
  }

  // 短期反转
  if (c.strev !== undefined) {
    if (c.strev >= 80) {
      reasons.push('短期反转信号强');
    } else if (c.strev >= 50) {
      reasons.push('短期反转信号一般');
    } else {
      reasons.push('短期反转信号弱');
    }
  }

  // 最大回撤
  if (c.drawdown !== undefined) {
    if (c.drawdown >= 80) {
      reasons.push('回撤较小，风险控制良好');
    } else if (c.drawdown >= 50) {
      reasons.push('回撤适中');
    } else {
      reasons.push('回撤较大，风险较高');
    }
  }

  // 市场状态
  if (c.regime !== undefined) {
    if (c.regime >= 80) {
      reasons.push('市场状态良好，适合操作');
    } else if (c.regime >= 50) {
      reasons.push('市场状态一般');
    } else {
      reasons.push('市场状态较差，需谨慎');
    }
  }

  // RSI值
  if (c.rsi !== undefined) {
    if (c.rsi < 30) {
      reasons.push(`RSI=${c.rsi.toFixed(1)}，处于超卖区域，可能反弹`);
    } else if (c.rsi > 70) {
      reasons.push(`RSI=${c.rsi.toFixed(1)}，处于超买区域，注意风险`);
    } else {
      reasons.push(`RSI=${c.rsi.toFixed(1)}，处于正常区间`);
    }
  }

  // 止损位
  if (c.stop !== undefined) {
    reasons.push(`止损位${c.stop.toFixed(2)}元，风险可控`);
  }

  return reasons;
}

function StockDetail({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  const reasons = generateReasons(candidate);
  const [smcData, setSmcData] = useState<any>(null);
  const [smcLoading, setSmcLoading] = useState(false);

  useEffect(() => {
    if (!candidate.code) return;
    setSmcLoading(true);
    api.tools.get<any>(`/smc/${candidate.code}`)
      .then(r => { if (r?.ok) setSmcData(r); })
      .catch(() => {})
      .finally(() => setSmcLoading(false));
  }, [candidate.code]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">{candidate.name} ({candidate.code})</h3>
            <p className="text-sm text-muted-foreground">入选理由分析</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-muted rounded">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {/* 基本信息 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="text-center p-3 bg-muted/30 rounded-lg">
              <div className="text-sm text-muted-foreground">现价</div>
              <div className="text-lg font-bold">{candidate.price.toFixed(2)}</div>
            </div>
            <div className="text-center p-3 bg-muted/30 rounded-lg">
              <div className="text-sm text-muted-foreground">评分</div>
              <div className="text-lg font-bold text-primary">{candidate.score.toFixed(1)}</div>
            </div>
            {candidate.E !== undefined && (
              <div className="text-center p-3 bg-muted/30 rounded-lg">
                <div className="text-sm text-muted-foreground">E价</div>
                <div className="text-lg font-bold">{candidate.E.toFixed(2)}</div>
              </div>
            )}
            {candidate.deviation !== undefined && (
              <div className="text-center p-3 bg-muted/30 rounded-lg">
                <div className="text-sm text-muted-foreground">偏差</div>
                <div className={`text-lg font-bold ${candidate.deviation >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                  {candidate.deviation.toFixed(2)}%
                </div>
              </div>
            )}
          </div>

          {/* 入选理由 */}
          <div className="mb-6">
            <h4 className="font-semibold mb-3 flex items-center gap-2">
              <Search className="h-4 w-4" />
              入选理由
            </h4>
            <div className="space-y-2">
              {reasons.map((reason, idx) => (
                <div key={idx} className="flex items-start gap-2 p-2 bg-muted/20 rounded">
                  <div className="w-1.5 h-1.5 rounded-full bg-primary mt-2 shrink-0" />
                  <span className="text-sm">{reason}</span>
                </div>
              ))}
            </div>
          </div>

          {/* SMC结构图 */}
          <div className="mb-6">
            <h4 className="font-semibold mb-3 flex items-center gap-2">
              <CandleIcon className="h-4 w-4" />
              SMC结构图
            </h4>
            {/* 图例 */}
            <div className="flex flex-wrap gap-3 mb-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="inline-block w-0 h-0 border-l-4 border-r-4 border-b-6 border-l-transparent border-r-transparent border-b-green-500" />BOS多(结构突破)</span>
              <span className="flex items-center gap-1"><span className="inline-block w-0 h-0 border-l-4 border-r-4 border-t-6 border-l-transparent border-r-transparent border-t-red-500" />BOS空</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rotate-45 bg-blue-500" />流动性扫盘</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-blue-500/20 border border-blue-500" />FVG(公允缺口)</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-purple-500/20 border border-purple-500 border-dashed" />OB(订单块)</span>
              <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 bg-amber-500/20 border border-amber-500 border-dotted" />OTE(最优入场区)</span>
            </div>
            {smcLoading ? (
              <div className="h-80 flex items-center justify-center text-muted-foreground">加载中...</div>
            ) : smcData?.klines ? (
              <SMCChart
                klines={smcData.klines}
                signals={smcData.signals || []}
                sweeps={smcData.sweeps || []}
                fvg_zones={smcData.fvg_zones || []}
                ob_zones={smcData.ob_zones || []}
                ote_zones={smcData.ote_zones || []}
                height={350}
              />
            ) : (
              <div className="h-80 flex items-center justify-center text-muted-foreground">暂无图表数据</div>
            )}
            {/* 分析建议 */}
            {smcData?.analysis && (
              <div className="mt-3 p-3 bg-muted/30 rounded-lg text-sm">
                <div className="flex items-center gap-4 mb-2 text-xs text-muted-foreground">
                  <span>日期: {smcData.analysis.date}</span>
                  <span>价格: {smcData.analysis.price}</span>
                  <span>趋势: {smcData.analysis.trend > 0 ? "上升" : smcData.analysis.trend < 0 ? "下降" : "震荡"}</span>
                  <span>MA20: {smcData.analysis.ma20}</span>
                  <span>MA60: {smcData.analysis.ma60}</span>
                  <span>RSI: {smcData.analysis.rsi}</span>
                </div>
                <div className="space-y-1 mb-2">
                  {smcData.analysis.points?.map((p: string, i: number) => (
                    <div key={i} className="flex items-start gap-1.5">
                      <span className="w-1 h-1 rounded-full bg-primary mt-1.5 shrink-0" />
                      <span>{p}</span>
                    </div>
                  ))}
                </div>
                <div className="font-medium text-primary">
                  建议: {smcData.analysis.suggestion}
                </div>
              </div>
            )}
          </div>

          {/* 评分明细 */}
          <div>
            <h4 className="font-semibold mb-3">评分明细</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
              {(c => {
                const ss = (c as any).structure_score;
                const fvg = (c as any).fvg_score;
                const ob = (c as any).ob_score;
                const liq = (c as any).liquidity_score;
                const ote = (c as any).ote_score;
                const vol = (c as any).vol_score;
                const s31 = (c as any).structure_3_1_score;
                if (ss === undefined && fvg === undefined) return null;
                return (
                  <>
                    {ss !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">结构(BOS/ChoCH)</span><span className="font-medium">{ss}/20</span></div>}
                    {fvg !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">FVG(公允缺口)</span><span className="font-medium">{fvg}/25</span></div>}
                    {ob !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">OB(订单块)</span><span className="font-medium">{ob}/20</span></div>}
                    {liq !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">流动性</span><span className="font-medium">{liq}/10</span></div>}
                    {ote !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">OTE(最优入场)</span><span className="font-medium">{ote}/15</span></div>}
                    {vol !== undefined && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">成交量</span><span className="font-medium">{vol}/10</span></div>}
                    {s31 !== undefined && s31 > 0 && <div className="flex justify-between p-2 bg-muted/20 rounded"><span className="text-muted-foreground">3-1结构</span><span className="font-medium">{s31}/5</span></div>}
                  </>
                );
              })(candidate)}
              {candidate.trend !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">趋势</span>
                  <span className="font-medium">{candidate.trend}</span>
                </div>
              )}
              {candidate.momentum !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">动量</span>
                  <span className="font-medium">{candidate.momentum}</span>
                </div>
              )}
              {candidate.volume_s !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">成交量</span>
                  <span className="font-medium">{candidate.volume_s}</span>
                </div>
              )}
              {candidate.volatility !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">波动率</span>
                  <span className="font-medium">{candidate.volatility}</span>
                </div>
              )}
              {candidate.liquidity !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">流动性</span>
                  <span className="font-medium">{candidate.liquidity}</span>
                </div>
              )}
              {candidate.rs !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">相对强度</span>
                  <span className="font-medium">{candidate.rs}</span>
                </div>
              )}
              {candidate.turnover !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">换手率</span>
                  <span className="font-medium">{candidate.turnover}</span>
                </div>
              )}
              {candidate.adx_s !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">ADX</span>
                  <span className="font-medium">{candidate.adx_s}</span>
                </div>
              )}
              {candidate.gtja_vp !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">量价背离</span>
                  <span className="font-medium">{candidate.gtja_vp}</span>
                </div>
              )}
              {candidate.gtja_cp !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">收盘位置</span>
                  <span className="font-medium">{candidate.gtja_cp}</span>
                </div>
              )}
              {candidate.high52w !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">52周新高</span>
                  <span className="font-medium">{candidate.high52w}</span>
                </div>
              )}
              {candidate.strev !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">短期反转</span>
                  <span className="font-medium">{candidate.strev}</span>
                </div>
              )}
              {candidate.retskew !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">收益偏态</span>
                  <span className="font-medium">{candidate.retskew}</span>
                </div>
              )}
              {candidate.drawdown !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">最大回撤</span>
                  <span className="font-medium">{candidate.drawdown}</span>
                </div>
              )}
              {candidate.var_s !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">VaR</span>
                  <span className="font-medium">{candidate.var_s}</span>
                </div>
              )}
              {candidate.regime !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">市场状态</span>
                  <span className="font-medium">{candidate.regime}</span>
                </div>
              )}
            </div>
          </div>

          {/* 关键指标 */}
          <div className="mt-6">
            <h4 className="font-semibold mb-3">关键指标</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm">
              {candidate.H !== undefined && candidate.H_date !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">最高价</span>
                  <span className="font-medium">{candidate.H.toFixed(2)} ({candidate.H_date})</span>
                </div>
              )}
              {candidate.L !== undefined && candidate.L_date !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">最低价</span>
                  <span className="font-medium">{candidate.L.toFixed(2)} ({candidate.L_date})</span>
                </div>
              )}
              {candidate.swing !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">摆动幅度</span>
                  <span className="font-medium">{candidate.swing.toFixed(1)}%</span>
                </div>
              )}
              {candidate.stop !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">止损位</span>
                  <span className="font-medium">{candidate.stop.toFixed(2)}</span>
                </div>
              )}
              {candidate.rsi !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">RSI</span>
                  <span className="font-medium">{candidate.rsi.toFixed(1)}</span>
                </div>
              )}
              {candidate.adx !== undefined && (
                <div className="flex justify-between p-2 bg-muted/20 rounded">
                  <span className="text-muted-foreground">ADX值</span>
                  <span className="font-medium">{candidate.adx.toFixed(1)}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StrategyTable({ candidates, columns, klineData, expandedKline, onKline, onBuy, onSelect, emptyText }: {
  candidates: Candidate[];
  columns: Column[];
  klineData: Record<string, PriceBar[]>;
  expandedKline: string | null;
  onKline: (code: string) => void;
  onBuy: (c: Candidate) => void;
  onSelect: (c: Candidate) => void;
  emptyText: string;
}) {
  if (candidates.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p className="mb-3">{emptyText}</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">排名</th>
            {columns.map(col => (
              <th key={col.key} className={`px-3 py-2 text-${col.align === "right" ? "right" : col.align === "center" ? "center" : "left"} font-medium`}>{col.label}</th>
            ))}
            <th className="px-3 py-2 text-center font-medium">K线</th>
            <th className="px-3 py-2 text-center font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c, i) => (
            <>
              <tr key={c.code} className="border-t">
                <td className="px-3 py-2 text-center text-muted-foreground">{i + 1}</td>
                {columns.map(col => (
                  <td key={col.key} className={`px-3 py-2 text-${col.align === "right" ? "right" : col.align === "center" ? "center" : "left"}`}>{col.render(c)}</td>
                ))}
                <td className="px-3 py-2 text-center">
                  <button onClick={() => onKline(c.code)} className="p-1 text-muted-foreground hover:text-primary rounded" title="查看K线">
                    <CandleIcon className="h-4 w-4" />
                  </button>
                </td>
                <td className="px-3 py-2 text-center">
                  <button onClick={() => onBuy(c)} className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700">买入</button>
                  <button onClick={() => onSelect(c)} className="ml-1 px-2 py-0.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700">详情</button>
                </td>
              </tr>
              {expandedKline === c.code && klineData[c.code] && (
                <tr key={`${c.code}-kline`}>
                  <td colSpan={columns.length + 3} className="px-4 py-3 bg-muted/10">
                    <CandlestickChart data={klineData[c.code]} height={360} />
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DailyScan() {
  const [market, setMarket] = useState<MarketStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fibCandidates, setFibCandidates] = useState<Candidate[]>([]);
  const [v5Candidates, setV5Candidates] = useState<Candidate[]>([]);
  const [ictCandidates, setIctCandidates] = useState<Candidate[]>([]);
  const [sentHeader, setSentHeader] = useState<any>(null);
  const [sentCandidates, setSentCandidates] = useState<any[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [scriptOutput, setScriptOutput] = useState<string | null>(null);
  const [noCache, setNoCache] = useState(false);
  const [klineData, setKlineData] = useState<Record<string, PriceBar[]>>({});
  const [expandedKline, setExpandedKline] = useState<string | null>(null);
  const [selectedStock, setSelectedStock] = useState<Candidate | null>(null);
  const [activeStrategy, setActiveStrategy] = useState<"fibonacci" | "v5" | "ict" | "sentiment">("fibonacci");
  const [decisionNotes, setDecisionNotes] = useState("");
  const [sentAi, setSentAi] = useState<Record<number, { phase: string; analysis: string; suggestion: string } | null>>({});
  const [sentAiLoading, setSentAiLoading] = useState<number | null>(null);
  const [sentAiError, setSentAiError] = useState<Record<number, string>>({});

  const handleSentAiAnalyze = async (step: number) => {
    setSentAiLoading(step);
    setSentAiError((e) => ({ ...e, [step]: "" }));
    try {
      const res = await api.tools.post<any>("/sentiment/ai-analyze", {
        step,
        header: sentHeader ?? {},
        candidates: sentCandidates,
      });
      if (res?.ok) {
        setSentAi((p) => ({ ...p, [step]: { phase: res.phase, analysis: res.analysis, suggestion: res.suggestion } }));
      } else {
        setSentAiError((e) => ({ ...e, [step]: res?.error || "分析失败" }));
      }
    } catch (e: any) {
      setSentAiError((er) => ({ ...er, [step]: e?.message || String(e) }));
    } finally {
      setSentAiLoading(null);
    }
  };

  const renderSentAi = (step: number) => {
    const data = sentAi[step];
    const loading = sentAiLoading === step;
    const err = sentAiError[step];
    return (
      <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50/40 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Brain className="h-4 w-4 text-violet-500" />
            <span className="text-sm font-medium text-violet-700">AI 阶段分析</span>
          </div>
          <button
            onClick={() => handleSentAiAnalyze(step)}
            disabled={loading}
            className="flex items-center gap-1 px-2.5 py-1 text-xs bg-violet-600 text-white rounded-md hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Brain className="h-3 w-3" />}
            {loading ? "分析中..." : data ? "重新分析" : "AI分析"}
          </button>
        </div>
        {data && (
          <div className="mt-2 space-y-1 text-sm">
            <p className="font-medium">阶段：<span className="text-violet-700">{data.phase}</span></p>
            <p className="text-muted-foreground leading-snug">{data.analysis}</p>
            <p className="text-violet-700 leading-snug">建议：{data.suggestion}</p>
          </div>
        )}
        {err && <p className="mt-1.5 text-xs text-red-500">{err}</p>}
      </div>
    );
  };

  const strategies = [
    { key: "fibonacci" as const, label: "斐波那契", icon: Search, count: fibCandidates.length },
    { key: "v5" as const, label: "V5趋势", icon: TrendingUp, count: v5Candidates.length },
    { key: "ict" as const, label: "ICT/SMC", icon: BarChart3, count: ictCandidates.length },
    { key: "sentiment" as const, label: "情绪选股", icon: Activity, count: sentCandidates.length },
  ];

  const fetchScanResults = async () => {
    try {
      const [fibData, v5Data, ictData, sentData] = await Promise.all([
        api.tools.get<any>("/scan-results?strategy=fibonacci"),
        api.tools.get<any>("/scan-results?strategy=v5"),
        api.tools.get<any>("/scan-results?strategy=ict"),
        api.tools.get<any>("/scan-results?strategy=sentiment_leader"),
      ]);
      const fib = fibData?.candidates || [];
      const v5 = v5Data?.candidates || [];
      const ict = ictData?.candidates || [];
      const sent = sentData?.candidates || [];
      setFibCandidates(fib);
      setV5Candidates(v5);
      setIctCandidates(ict);
      setSentCandidates(sent);
      setSentHeader(sentData?.mainlines && sentData.mainlines.length ? sentData : null);
      setNoCache(fib.length === 0 && v5.length === 0 && ict.length === 0 && sent.length === 0);
      setActiveStrategy((cur) => {
        const counts: Record<string, number> = { fibonacci: fib.length, v5: v5.length, ict: ict.length, sentiment: sent.length };
        if (counts[cur] && counts[cur] > 0) return cur;
        if (fib.length) return "fibonacci";
        if (v5.length) return "v5";
        if (ict.length) return "ict";
        if (sent.length) return "sentiment";
        return "fibonacci";
      });
    } catch (e) {
      setNoCache(true);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const market = await api.tools.get<any>("/market/realtime");
      setMarket(market);
      await fetchScanResults();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateData = async () => {
    setUpdating(true);
    try {
      const json = await api.tools.post<any>("/update-data");
      if (json.ok) {
        alert(`数据更新完成: ${json.message}`);
      } else {
        alert(`更新失败: ${json.message || "未知错误"}`);
      }
    } catch (e: any) {
      alert(`更新失败: ${e.message}`);
    } finally {
      setUpdating(false);
    }
  };

  const handleBuy = async (code: string, name: string, strategy: string, extra: Record<string, any>) => {
    try {
      const data = await api.tools.post<any>(`/stock/${code}/buy`, { strategy, name, ...extra });
      alert(data.message);
    } catch (e: any) {
      alert(`买入失败: ${e.message}`);
    }
  };

  const fetchKline = async (code: string) => {
    if (klineData[code]) {
      setExpandedKline(expandedKline === code ? null : code);
      return;
    }
    try {
      const data = await api.tools.get<any>(`/stock/${code}`);
      const bars: PriceBar[] = (data.kline || []).reverse().map((r: any) => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume,
      }));
      setKlineData((prev) => ({ ...prev, [code]: bars }));
      setExpandedKline(code);
    } catch {}
  };

  const handleRunScan = async (script: string) => {
    setRunning(script);
    setScriptOutput("执行中...");
    try {
      const data = await api.tools.post<any>("/run-script", { script });
      const taskId = data.task_id;
      if (!taskId) {
        setScriptOutput("启动失败");
        setRunning(null);
        return;
      }
      const poll = async () => {
        const d = await api.tools.get<any>(`/run-script/${taskId}`);
        setScriptOutput(d.output || "");
        if (d.output && d.output.includes("执行中")) {
          setTimeout(poll, 3000);
        } else {
          setRunning(null);
          await fetchScanResults();
        }
      };
      setTimeout(poll, 3000);
    } catch (e: any) {
      setScriptOutput(`失败: ${e.message}`);
      setRunning(null);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const stats = market;
  const upRatio = stats && stats.total ? (stats.up / stats.total * 100).toFixed(1) : "0";
  const downRatio = stats && stats.total ? (stats.down / stats.total * 100).toFixed(1) : "0";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">每日选股</h1>
          <p className="text-sm text-muted-foreground mt-1">策略扫描与市场概览</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleUpdateData}
            disabled={updating}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <Download className={`h-4 w-4 ${updating ? "animate-spin" : ""}`} />
            {updating ? "更新中..." : "更新数据"}
          </button>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="border border-red-200 bg-red-50 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Market Stats */}
      <div className="grid gap-4 md:grid-cols-5">
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">总数</div>
          <p className="text-xl font-bold">{stats?.total || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-red-500" />
            上涨
          </div>
          <p className="text-xl font-bold text-red-600">{stats?.up || 0}</p>
          <p className="text-xs text-muted-foreground">{upRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <TrendingUp className="h-4 w-4 text-green-500 rotate-180" />
            下跌
          </div>
          <p className="text-xl font-bold text-green-600">{stats?.down || 0}</p>
          <p className="text-xs text-muted-foreground">{downRatio}%</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">涨停</div>
          <p className="text-xl font-bold text-red-600">{stats?.limit_up || 0}</p>
        </div>
        <div className="border rounded-lg p-4 bg-card">
          <div className="text-sm text-muted-foreground mb-1">跌停</div>
          <p className="text-xl font-bold text-green-600">{stats?.limit_down || 0}</p>
        </div>
      </div>

      {/* Market Breadth Bar */}
      {stats && stats.total > 0 && (
        <div className="border rounded-lg p-4 bg-card">
          <h2 className="font-semibold mb-3">市场宽度</h2>
          <div className="flex h-6 rounded-full overflow-hidden bg-muted">
            <div
              className="bg-red-500 transition-all"
              style={{ width: `${(stats.up / stats.total) * 100}%` }}
              title={`上涨 ${stats.up}`}
            />
            <div
              className="bg-gray-400 transition-all"
              style={{ width: `${((stats.flat || 0) / stats.total) * 100}%` }}
              title={`平盘 ${stats.flat || 0}`}
            />
            <div
              className="bg-green-500 transition-all"
              style={{ width: `${(stats.down / stats.total) * 100}%` }}
              title={`下跌 ${stats.down}`}
            />
          </div>
          <div className="flex justify-between mt-2 text-xs text-muted-foreground">
            <span className="text-red-600">上涨 {stats.up}</span>
            <span>平盘 {stats.flat || 0}</span>
            <span className="text-green-600">下跌 {stats.down}</span>
          </div>
        </div>
      )}

      {/* 缓存为空时显示执行入口 */}
      {noCache && !running && !loading && (
        <div className="border rounded-lg p-8 bg-card">
          <h2 className="text-lg font-semibold mb-4 text-center">今日尚无选股结果</h2>
          <div className="grid gap-3 md:grid-cols-4 max-w-3xl mx-auto">
            <button
              onClick={() => handleRunScan("fibonacci")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <Search className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">斐波那契选股</p>
                <p className="text-xs text-muted-foreground">约需1-2分钟</p>
              </div>
            </button>
            <button
              onClick={() => handleRunScan("v5")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <TrendingUp className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">趋势选股V5</p>
                <p className="text-xs text-muted-foreground">约需1-2分钟</p>
              </div>
            </button>
            <button
              onClick={() => handleRunScan("ict")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <BarChart3 className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">ICT/SMC选股</p>
                <p className="text-xs text-muted-foreground">约需4-5分钟</p>
              </div>
            </button>
            <button
              onClick={() => handleRunScan("sentiment_leader")}
              className="flex items-center gap-3 p-4 border rounded-lg hover:bg-muted transition-colors text-left"
            >
              <TrendingUp className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">短线情绪选股</p>
                <p className="text-xs text-muted-foreground">约需1-2分钟</p>
              </div>
            </button>
          </div>
        </div>
      )}

      {running && (
        <div className="border rounded-lg bg-card overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30 flex items-center gap-2">
            <div className="animate-spin h-4 w-4 border-2 border-primary border-t-transparent rounded-full" />
            <span className="font-semibold text-sm">
              {running === "fibonacci" ? "斐波那契" : running === "ict" ? "ICT/SMC" : running === "v5" ? "V5趋势" : running === "sentiment_leader" ? "短线情绪" : ""}选股执行中...
            </span>
          </div>
          <pre className="p-4 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-[400px] text-muted-foreground">
            {scriptOutput || "等待输出..."}
          </pre>
        </div>
      )}

      {/* 选股结果（并列 Tab 切换） */}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div className="flex items-center justify-between border-b px-4 py-3 bg-muted/30">
          <h2 className="font-semibold">选股结果</h2>
          <div className="flex items-center gap-1">
            {strategies.map(({ key, label, icon: Icon, count }) => (
              <button
                key={key}
                onClick={() => setActiveStrategy(key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
                  activeStrategy === key
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
                <span className="text-xs opacity-70">{count > 0 ? `(${count})` : ""}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="px-4 py-3 border-b bg-muted/20 flex items-center justify-between">
          <h3 className="text-sm font-medium">
            {activeStrategy === "fibonacci" ? "斐波那契选股结果" : activeStrategy === "v5" ? "V5趋势选股结果" : activeStrategy === "sentiment" ? "短线情绪选股结果" : "ICT/SMC选股结果"}
            {(() => {
              const n = activeStrategy === "fibonacci" ? fibCandidates.length : activeStrategy === "v5" ? v5Candidates.length : activeStrategy === "sentiment" ? sentCandidates.length : ictCandidates.length;
              return n > 0 ? `（${n} 只）` : "";
            })()}
          </h3>
          <button
            onClick={() => handleRunScan(activeStrategy)}
            disabled={running === activeStrategy}
            className="flex items-center gap-1 px-3 py-1 text-xs border rounded-md hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${running === activeStrategy ? "animate-spin" : ""}`} />
            重新选股
          </button>
        </div>
        {activeStrategy === "sentiment" && (
          <div className="px-4 pb-3">
            <RunLogPanel subdir="stock_selection" name="sentiment_leader" title="情绪选股运行日志" />
          </div>
        )}
        {!running && (
          <div className="px-4 py-3">
            {activeStrategy === "fibonacci" && (
              <StrategyTable
                candidates={fibCandidates}
                columns={[
                  { key: "code", label: "代码", render: c => <span className="font-mono cursor-pointer text-primary hover:underline">{c.code}</span> },
                  { key: "name", label: "名称", render: c => c.name },
                  { key: "price", label: "现价", align: "right", render: c => c.price.toFixed(2) },
                  { key: "E", label: "E价", align: "right", render: c => c.E?.toFixed(2) ?? "-" },
                  { key: "deviation", label: "偏差%", align: "right", render: c => <span className={(c.deviation ?? 0) >= 0 ? "text-red-600" : "text-green-600"}>{c.deviation?.toFixed(2) ?? "-"}%</span> },
                  { key: "score", label: "评分", align: "right", render: c => <span className="font-medium">{c.score.toFixed(1)}</span> },
                  { key: "swing", label: "摆动%", align: "right", render: c => `${c.swing?.toFixed(1) ?? "-"}%` },
                  { key: "stop", label: "止损", align: "right", render: c => <span className="text-muted-foreground">{c.stop?.toFixed(2) ?? "-"}</span> },
                  { key: "H_date", label: "H日期", align: "center", render: c => <span className="text-xs">{c.H_date}</span> },
                  { key: "L_date", label: "L日期", align: "center", render: c => <span className="text-xs">{c.L_date}</span> },
                ]}
                klineData={klineData}
                expandedKline={expandedKline}
                onKline={fetchKline}
                onBuy={c => handleBuy(c.code, c.name, "fibonacci", { price: c.price, E: c.E, stop: c.stop, score: c.score })}
                onSelect={setSelectedStock}
                emptyText="暂无斐波那契选股结果"
              />
            )}
            {activeStrategy === "v5" && (
              <StrategyTable
                candidates={v5Candidates}
                columns={[
                  { key: "code", label: "代码", render: c => <span className="font-mono cursor-pointer text-primary hover:underline">{c.code}</span> },
                  { key: "name", label: "名称", render: c => c.name },
                  { key: "price", label: "现价", align: "right", render: c => c.price.toFixed(2) },
                  { key: "score", label: "评分", align: "right", render: c => <span className="font-medium">{c.score.toFixed(1)}</span> },
                ]}
                klineData={klineData}
                expandedKline={expandedKline}
                onKline={fetchKline}
                onBuy={c => handleBuy(c.code, c.name, "v5", { price: c.price, score: c.score })}
                onSelect={setSelectedStock}
                emptyText="暂无V5趋势选股结果"
              />
            )}
            {activeStrategy === "ict" && (
              <StrategyTable
                candidates={ictCandidates}
                columns={[
                  { key: "code", label: "代码", render: c => <span className="font-mono cursor-pointer text-primary hover:underline">{c.code}</span> },
                  { key: "name", label: "名称", render: c => c.name },
                  { key: "price", label: "现价", align: "right", render: c => c.price.toFixed(2) },
                  { key: "score", label: "总分", align: "right", render: c => <span className="font-medium">{c.score.toFixed(1)}</span> },
                  { key: "structure_score", label: "结构", align: "right", render: c => (c as any).structure_score?.toFixed(0) ?? "-" },
                  { key: "fvg_score", label: "FVG", align: "right", render: c => (c as any).fvg_score?.toFixed(0) ?? "-" },
                  { key: "ob_score", label: "OB", align: "right", render: c => (c as any).ob_score?.toFixed(0) ?? "-" },
                  { key: "liquidity_score", label: "流动性", align: "right", render: c => (c as any).liquidity_score?.toFixed(0) ?? "-" },
                  { key: "ote_score", label: "OTE", align: "right", render: c => (c as any).ote_score?.toFixed(0) ?? "-" },
                  { key: "vol_score", label: "量能", align: "right", render: c => (c as any).vol_score?.toFixed(0) ?? "-" },
                ]}
                klineData={klineData}
                expandedKline={expandedKline}
                onKline={fetchKline}
                onBuy={c => handleBuy(c.code, c.name, "ict", { price: c.price, score: c.score, structure: (c as any).structure, sweep_level: (c as any).sweep_level })}
                onSelect={setSelectedStock}
                emptyText="暂无ICT/SMC选股结果"
              />
            )}
            {activeStrategy === "sentiment" && (
              <div className="space-y-5">
                {!sentHeader && sentCandidates.length === 0 && (
                  <div className="p-6 text-center text-muted-foreground">暂无短线情绪选股结果，请点击上方「重新选股」或先运行短线情绪选股</div>
                )}
                {sentHeader && (
                  <>
                    <RunLogPanel subdir="ai_analysis" name="sentiment_ai_analyze" title="情绪周期AI分析运行日志" autoRefresh={10000} />
                    {/* Step 1 情绪周期 */}
                    <div className="border rounded-lg p-4">
                      <h4 className="font-semibold mb-3 text-base flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary text-primary-foreground text-xs">1</span>
                        情绪周期
                      </h4>
                      <div className="flex flex-wrap items-center gap-4">
                        <span className={`inline-flex px-3 py-1 rounded-full text-sm font-semibold ${
                          sentHeader.cycle === "主升" ? "bg-red-100 text-red-700" :
                          sentHeader.cycle === "启动" ? "bg-orange-100 text-orange-700" :
                          sentHeader.cycle === "分歧" ? "bg-amber-100 text-amber-700" :
                          "bg-blue-100 text-blue-700"
                        }`}>
                          当前情绪：{sentHeader.cycle}
                        </span>
                        {sentHeader.breadth && (
                          <div className="flex flex-wrap gap-2 text-sm text-muted-foreground">
                            <span className="px-2 py-1 bg-muted/40 rounded">涨停 {sentHeader.breadth.limit_up}</span>
                            <span className="px-2 py-1 bg-muted/40 rounded">涨幅&gt;5% {sentHeader.breadth.gainer}</span>
                            <span className="px-2 py-1 bg-muted/40 rounded">最高连板 {sentHeader.breadth.max_streak}</span>
                          </div>
                        )}
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        操作参考：启动/主升→可参与；分歧→低位切换；退潮→空仓或极小仓位试错。
                      </p>
                      {renderSentAi(1)}
                    </div>

                    {/* Step 2 主线板块 */}
                    <div className="border rounded-lg p-4">
                      <h4 className="font-semibold mb-3 text-base flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary text-primary-foreground text-xs">2</span>
                        主线板块
                      </h4>
                      {(!sentHeader.mainlines || sentHeader.mainlines.length === 0) ? (
                        <div className="text-sm text-muted-foreground">今日无成立主线（板块内个股不足）</div>
                      ) : (
                        <div className="grid gap-2 md:grid-cols-3">
                          {sentHeader.mainlines.map((ml: any) => (
                            <div key={ml.concept} className="border rounded-lg p-3 bg-muted/10">
                              <div className="flex items-center justify-between">
                                <span className="font-medium text-sm">{ml.concept}</span>
                                <span className="text-xs text-primary">强度 {ml.score}</span>
                              </div>
                              <div className="mt-1 text-xs text-muted-foreground space-x-3">
                                <span>{ml.n} 家</span>
                                <span>涨停 {ml.zt_n}</span>
                                <span>最高 {ml.max_streak}板</span>
                                <span>均涨 {ml.avg_chg}%</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      {renderSentAi(2)}
                    </div>

                    {/* Step 3 个股精选 */}
                    <div className="border rounded-lg p-4">
                      <h4 className="font-semibold mb-3 text-base flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary text-primary-foreground text-xs">3</span>
                        个股精选（按主线/地位排序）
                      </h4>
                      {sentCandidates.length === 0 && (
                        <div className="text-sm text-muted-foreground">无候选（涨幅未达阈值）</div>
                      )}
                      {sentCandidates.length > 0 && (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead className="bg-muted/40 text-xs text-muted-foreground">
                              <tr>
                                <th className="px-3 py-2 text-left font-medium">主线</th>
                                <th className="px-3 py-2 text-left font-medium">地位</th>
                                <th className="px-3 py-2 text-left font-medium">代码</th>
                                <th className="px-3 py-2 text-left font-medium">名称</th>
                                <th className="px-3 py-2 text-right font-medium">现价</th>
                                <th className="px-3 py-2 text-right font-medium">涨幅</th>
                                <th className="px-3 py-2 text-center font-medium">连板</th>
                                <th className="px-3 py-2 text-center font-medium">上板时间</th>
                                <th className="px-3 py-2 text-center font-medium">操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sentCandidates.map((c, i) => {
                                const s = c.stock || {};
                                const isZt = !!s.is_zt;
                                const roleTag =
                                  s.role === "龙" ? <span className="text-red-600 font-semibold">龙头</span> :
                                  s.role === "板块龙头" ? <span className="text-orange-600 font-medium">板块龙头</span> :
                                  s.role === "补涨龙" ? <span className="text-amber-600 font-medium">补涨龙</span> :
                                  s.role === "日内先锋" ? <span className="text-blue-600 font-medium">日内先锋</span> :
                                  <span className="text-muted-foreground">{s.role || "跟风"}</span>;
                                return (
                                  <Fragment key={`${c.mainline}-${s.code}-${i}`}>
                                    <tr className="border-t">
                                      <td className="px-3 py-2">
                                        <span className="inline-flex px-2 py-0.5 rounded bg-primary/10 text-primary text-xs">{c.mainline}</span>
                                      </td>
                                      <td className="px-3 py-2">{roleTag}</td>
                                      <td className="px-3 py-2 font-mono">{s.code}</td>
                                      <td className="px-3 py-2">{s.name}</td>
                                      <td className="px-3 py-2 text-right font-mono">{s.price?.toFixed(2)}</td>
                                      <td className="px-3 py-2 text-right">
                                        <span className={isZt ? "text-red-600 font-semibold" : "text-red-600"}>{isZt ? "涨停" : `+${s.chg?.toFixed(2)}%`}</span>
                                      </td>
                                      <td className="px-3 py-2 text-center">{s.streak ? `${s.streak}板` : "首板"}</td>
                                      <td className="px-3 py-2 text-center text-muted-foreground">{s.ltime || "--:--"}</td>
                                      <td className="px-3 py-2 text-center">
                                        <button onClick={() => handleBuy(s.code, s.name, "sentiment_leader", { price: s.price, score: c.score })} className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700">买入</button>
                                        <button onClick={() => fetchKline(s.code)} className="ml-1 p-1 text-muted-foreground hover:text-primary rounded" title="查看K线">
                                          <CandleIcon className="h-4 w-4 inline" />
                                        </button>
                                      </td>
                                    </tr>
                                    {expandedKline === s.code && klineData[s.code] && (
                                      <tr>
                                        <td colSpan={9} className="px-4 py-3 bg-muted/10">
                                          <CandlestickChart data={klineData[s.code]} height={360} />
                                        </td>
                                      </tr>
                                    )}
                                  </Fragment>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                    {renderSentAi(3)}

                    {/* Step 4 决策区（结论留人判断） */}
                    <div className="border rounded-lg p-4 border-dashed">
                      <h4 className="font-semibold mb-3 text-base flex items-center gap-2">
                        <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-primary text-primary-foreground text-xs">4</span>
                        决策区（结论由你判断）
                      </h4>
                      <p className="text-sm text-muted-foreground mb-3">
                        以上仅为客观数据。请依据情绪周期决定「做不做」，依据主线板块决定「在哪做」，依据个股地位决定「做哪个」。
                        回避：非主线杂毛 / 中位股（退潮期3-4板）/ 缩量加速一字板 / 跟风后排。
                      </p>
                      <textarea
                        value={decisionNotes}
                        onChange={(e) => setDecisionNotes(e.target.value)}
                        placeholder="记录你的结论与理由（仅保存在本地页面，刷新后清空）..."
                        className="w-full p-3 border rounded-md text-sm min-h-[100px] bg-muted/20 resize-y"
                      />
                      {renderSentAi(4)}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 股票详情弹窗 */}
      {selectedStock && (
        <StockDetail candidate={selectedStock} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  );
}

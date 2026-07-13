import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { useModalStore } from "../../stores/modal";
import { IntradaySparkline } from "@/components/charts/IntradaySparkline";

interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Indicators {
  ma5: number;
  ma10: number;
  ma20: number;
  ma60: number;
  rsi14: number;
  avg_volume_5: number;
  avg_volume_20: number;
}

export function StockDetailPanel() {
  const { stockCode, close } = useModalStore();
  const [kline, setKline] = useState<KlineBar[]>([]);
  const [indicators, setIndicators] = useState<Indicators | null>(null);
  const [name, setName] = useState("");
  const [price, setPrice] = useState(0);
  const [changePct, setChangePct] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!stockCode) return;
    setLoading(true);
    setKline([]);
    setIndicators(null);

    Promise.all([
      api.tools.get<any>(`/stock/${stockCode}`),
      api.tools.get<any>(`/stock/${stockCode}/indicators`),
      api.tools.get<any>(`/prices?codes=${stockCode}`),
    ])
      .then(([klineData, indData, priceData]) => {
        setKline(klineData.kline || []);
        setName(klineData.name || "");
        setIndicators(indData.indicators || null);
        const pi = priceData.prices?.[stockCode] || {};
        setPrice(pi.price || 0);
        setChangePct(pi.change_pct || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [stockCode]);

  if (!stockCode) return null;

  const latest = kline?.[0];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={close} />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-[420px] bg-card border-l shadow-xl z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-card border-b px-5 py-4 flex items-center justify-between z-10">
          <div>
            <h3 className="font-bold text-lg">{name || stockCode}</h3>
            <span className="text-xs text-muted-foreground font-mono">{stockCode}</span>
          </div>
          <div className="flex items-center gap-4">
            {price > 0 && (
              <div className="text-right">
                <p className={`text-xl font-bold ${changePct >= 0 ? "text-red-600" : "text-green-600"}`}>
                  {price.toFixed(2)}
                </p>
                <p className={`text-xs ${changePct >= 0 ? "text-red-600" : "text-green-600"}`}>
                  {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                </p>
              </div>
            )}
            <button onClick={close} className="p-1 hover:bg-muted rounded">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-muted-foreground">加载中...</div>
        ) : (
          <div className="p-5 space-y-5">
            {/* 分时图 */}
            <div className="border rounded-lg p-3 bg-muted/10">
              <h4 className="text-sm font-medium mb-2">今日分时</h4>
              <div className="flex justify-center">
                <IntradaySparkline code={stockCode} width={360} height={160} />
              </div>
            </div>

            {/* K-line summary */}
            {latest && (
              <div className="border rounded-lg p-4 bg-muted/30">
                <h4 className="text-sm font-medium mb-3">近30日K线概览</h4>
                <div className="grid grid-cols-4 gap-3 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs">最新收盘</span>
                    <p className="font-mono font-medium">{latest.close.toFixed(2)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">最高</span>
                    <p className="font-mono font-medium text-red-600">
                      {Math.max(...kline.map((k) => k.high)).toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">最低</span>
                    <p className="font-mono font-medium text-green-600">
                      {Math.min(...kline.map((k) => k.low)).toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">区间涨幅</span>
                    <p className={`font-mono font-medium ${
                      kline.length >= 2 && kline[0].close >= kline[kline.length - 1].close
                        ? "text-red-600" : "text-green-600"
                    }`}>
                      {kline.length >= 2
                        ? ((kline[0].close - kline[kline.length - 1].close) / kline[kline.length - 1].close * 100).toFixed(2) + "%"
                        : "-"}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Technical Indicators */}
            {indicators && (
              <div className="border rounded-lg p-4">
                <h4 className="text-sm font-medium mb-3">技术指标</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">MA5</span>
                    <span className="font-mono">{indicators.ma5?.toFixed(2) || "-"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">MA10</span>
                    <span className="font-mono">{indicators.ma10?.toFixed(2) || "-"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">MA20</span>
                    <span className="font-mono">{indicators.ma20?.toFixed(2) || "-"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">MA60</span>
                    <span className="font-mono">{indicators.ma60?.toFixed(2) || "-"}</span>
                  </div>
                  <div className="border-t pt-2 mt-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">RSI(14)</span>
                      <span className={`font-mono font-medium ${
                        indicators.rsi14 > 70 ? "text-red-600" :
                        indicators.rsi14 < 30 ? "text-green-600" : ""
                      }`}>
                        {indicators.rsi14?.toFixed(1) || "-"}
                      </span>
                    </div>
                  </div>
                  <div className="border-t pt-2 mt-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">5日均量</span>
                      <span className="font-mono">{formatVol(indicators.avg_volume_5)}</span>
                    </div>
                    <div className="flex justify-between mt-1">
                      <span className="text-muted-foreground">20日均量</span>
                      <span className="font-mono">{formatVol(indicators.avg_volume_20)}</span>
                    </div>
                    {indicators.avg_volume_5 > 0 && indicators.avg_volume_20 > 0 && (
                      <div className="flex justify-between mt-1">
                        <span className="text-muted-foreground">量比</span>
                        <span className={`font-mono font-medium ${
                          indicators.avg_volume_5 / indicators.avg_volume_20 > 1.5 ? "text-red-600" : ""
                        }`}>
                          {(indicators.avg_volume_5 / indicators.avg_volume_20).toFixed(2)}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Recent K-line table */}
            {kline.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <h4 className="text-sm font-medium p-4 pb-2">近期K线</h4>
                <table className="w-full text-xs">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-4 py-2 text-left">日期</th>
                      <th className="px-2 py-2 text-right">开盘</th>
                      <th className="px-2 py-2 text-right">最高</th>
                      <th className="px-2 py-2 text-right">最低</th>
                      <th className="px-2 py-2 text-right">收盘</th>
                      <th className="px-4 py-2 text-right">成交量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kline.slice(0, 10).map((bar) => (
                      <tr key={bar.date} className="border-t">
                        <td className="px-4 py-1.5 font-mono">{bar.date}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{bar.open.toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-red-600">{bar.high.toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-green-600">{bar.low.toFixed(2)}</td>
                        <td className="px-2 py-1.5 text-right font-mono font-medium">{bar.close.toFixed(2)}</td>
                        <td className="px-4 py-1.5 text-right font-mono">{formatVol(bar.volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function formatVol(v: number): string {
  if (!v) return "-";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + "万";
  return v.toFixed(0);
}

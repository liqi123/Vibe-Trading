import { useState } from "react";
import { Calculator, ArrowRight } from "lucide-react";

function RunawayPriceCalc() {
  const [high, setHigh] = useState("");
  const [low, setLow] = useState("");
  const [open, setOpen] = useState("");
  const [close, setClose] = useState("");
  const [buyPrice, setBuyPrice] = useState("");

  const h = parseFloat(high) || 0;
  const l = parseFloat(low) || 0;
  const o = parseFloat(open) || 0;
  const c = parseFloat(close) || 0;
  const bp = parseFloat(buyPrice) || 0;

  const runaway = (h + l + o + c) / 4;
  const shipPrice = bp > 0 ? 2 * runaway - bp : 0;

  return (
    <div className="border rounded-lg p-5 bg-card space-y-4">
      <h3 className="font-semibold flex items-center gap-2">
        <Calculator className="h-4 w-4 text-orange-500" />
        跑路价 / 出货价
      </h3>
      <p className="text-xs text-muted-foreground">跑路价 = (H+L+O+C)/4，出货价 = 2×跑路价 - 买入价</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground">最高价 (H)</label>
          <input value={high} onChange={e => setHigh(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">最低价 (L)</label>
          <input value={low} onChange={e => setLow(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">开盘价 (O)</label>
          <input value={open} onChange={e => setOpen(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">收盘价 (C)</label>
          <input value={close} onChange={e => setClose(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground">买入价（计算出货价时填）</label>
        <input value={buyPrice} onChange={e => setBuyPrice(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
      </div>
      <div className="flex items-center gap-4 pt-2 border-t">
        <div>
          <span className="text-xs text-muted-foreground">跑路价</span>
          <p className="text-lg font-bold text-orange-600">{runaway > 0 ? runaway.toFixed(2) : "-"}</p>
        </div>
        {bp > 0 && (
          <>
            <ArrowRight className="h-4 w-4 text-muted-foreground" />
            <div>
              <span className="text-xs text-muted-foreground">出货价</span>
              <p className="text-lg font-bold text-green-600">{shipPrice.toFixed(2)}</p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">预期收益</span>
              <p className={`text-lg font-bold ${(shipPrice - bp) / bp >= 0 ? "text-green-600" : "text-red-600"}`}>
                {((shipPrice - bp) / bp * 100).toFixed(2)}%
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FibonacciCalc() {
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");

  const l = parseFloat(low) || 0;
  const h = parseFloat(high) || 0;
  const range = h - l;

  const levels = [
    { ratio: 0.236, label: "23.6%" },
    { ratio: 0.382, label: "38.2%" },
    { ratio: 0.5, label: "50%" },
    { ratio: 0.618, label: "61.8%" },
    { ratio: 0.786, label: "78.6%" },
  ];

  return (
    <div className="border rounded-lg p-5 bg-card space-y-4">
      <h3 className="font-semibold flex items-center gap-2">
        <Calculator className="h-4 w-4 text-blue-500" />
        斐波那契回撤
      </h3>
      <p className="text-xs text-muted-foreground">输入一段行情的高低点，计算各斐波那契回撤位</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground">低点 (L)</label>
          <input value={low} onChange={e => setLow(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">高点 (H)</label>
          <input value={high} onChange={e => setHigh(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
      </div>
      {l > 0 && h > l && (
        <div className="space-y-2 pt-2 border-t">
          {levels.map(({ ratio, label }) => {
            const price = h - range * ratio;
            return (
              <div key={ratio} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-mono font-medium">{price.toFixed(2)}</span>
              </div>
            );
          })}
          <div className="flex items-center justify-between text-sm font-bold pt-1 border-t">
            <span className="text-muted-foreground">E 价 (61.8%)</span>
            <span className="font-mono text-primary">{(h - range * 0.618).toFixed(2)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function PriceRangeCalc() {
  const [buyPrice, setBuyPrice] = useState("");
  const [stopPct, setStopPct] = useState("-3");
  const [targetPct, setTargetPct] = useState("10");

  const bp = parseFloat(buyPrice) || 0;
  const sp = parseFloat(stopPct) || 0;
  const tp = parseFloat(targetPct) || 0;

  return (
    <div className="border rounded-lg p-5 bg-card space-y-4">
      <h3 className="font-semibold flex items-center gap-2">
        <Calculator className="h-4 w-4 text-green-500" />
        止损止盈计算
      </h3>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-muted-foreground">买入价</label>
          <input value={buyPrice} onChange={e => setBuyPrice(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">止损 %</label>
          <input value={stopPct} onChange={e => setStopPct(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">止盈 %</label>
          <input value={targetPct} onChange={e => setTargetPct(e.target.value)} className="w-full mt-1 px-3 py-1.5 text-sm border rounded bg-background outline-none focus:ring-2 focus:ring-primary/30" />
        </div>
      </div>
      {bp > 0 && (
        <div className="flex items-center gap-6 pt-2 border-t">
          <div>
            <span className="text-xs text-muted-foreground">止损价</span>
            <p className="text-lg font-bold text-red-600">{(bp * (1 + sp / 100)).toFixed(2)}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">止盈价</span>
            <p className="text-lg font-bold text-green-600">{(bp * (1 + tp / 100)).toFixed(2)}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">盈亏比</span>
            <p className="text-lg font-bold">{tp !== 0 && sp !== 0 ? (Math.abs(tp / sp)).toFixed(2) : "-"}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export function CalcTools() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">计算工具</h1>
        <p className="text-sm text-muted-foreground mt-1">实用价格计算</p>
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <RunawayPriceCalc />
        <FibonacciCalc />
        <PriceRangeCalc />
      </div>
    </div>
  );
}

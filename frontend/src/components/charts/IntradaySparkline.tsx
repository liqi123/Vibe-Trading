import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

interface IntradayBar {
  t: string;
  p: number;
}

interface Props {
  code: string;
  width?: number;
  height?: number;
}

export function IntradaySparkline({ code, width = 80, height = 28 }: Props) {
  const [bars, setBars] = useState<IntradayBar[]>([]);
  const [loaded, setLoaded] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    api.tools.get<any>(`/stock/${code}/intraday`)
      .then(data => {
        if (!mountedRef.current) return;
        setBars(data.bars || []);
        setLoaded(true);
      })
      .catch(() => {
        if (mountedRef.current) setLoaded(true);
      });
    return () => { mountedRef.current = false; };
  }, [code]);

  if (!loaded) return <div style={{ width, height }} />;

  const prices = bars.map(b => b.p);
  if (prices.length < 2) {
    return <div style={{ width, height }} className="text-[8px] text-muted-foreground flex items-center justify-center">--</div>;
  }

  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const range = maxP - minP || 1;
  const pad = range * 0.08;
  const yMin = minP - pad;
  const yMax = maxP + pad;
  const yRange = yMax - yMin;

  const px = (i: number) => (i / (prices.length - 1)) * width;
  const py = (v: number) => ((yMax - v) / yRange) * height;

  const firstY = py(prices[0]);
  const pathD = prices.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p).toFixed(1)}`).join("");
  const areaD = `${pathD}L${px(prices.length - 1).toFixed(1)},${firstY.toFixed(1)}L${px(0).toFixed(1)},${firstY.toFixed(1)}Z`;

  const isUp = prices[prices.length - 1] >= prices[0];
  const strokeColor = isUp ? "#dc2626" : "#16a34a";
  const fillColor = isUp ? "rgba(220,38,38,0.08)" : "rgba(22,163,74,0.08)";

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="inline-block">
      <path d={areaD} fill={fillColor} />
      <path d={pathD} fill="none" stroke={strokeColor} strokeWidth={1} />
    </svg>
  );
}

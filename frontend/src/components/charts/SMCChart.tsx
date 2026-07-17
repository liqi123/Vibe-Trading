import { useEffect, useRef, useMemo } from "react";
import { echarts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";

interface Kline {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Signal {
  time: string;
  type: string;
  direction: string;
  price: number;
}

interface Sweep {
  time: string;
  direction: string;
  price: number;
}

interface FVGZone {
  time: string;
  type: string;
  top: number;
  bottom: number;
}

interface OBZone {
  start: string;
  end: string;
  top: number;
  bottom: number;
  type: string;
}

interface OTEZone {
  start: string;
  end: string;
  top: number;
  bottom: number;
}

interface Props {
  klines: Kline[];
  signals: Signal[];
  sweeps: Sweep[];
  fvg_zones: FVGZone[];
  ob_zones: OBZone[];
  ote_zones: OTEZone[];
  height?: number;
}

export function SMCChart({ klines, signals, sweeps, fvg_zones, ob_zones, ote_zones, height = 400 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const { dark } = useDarkMode();

  const dates = useMemo(() => klines.map(k => k.time), [klines]);
  const candleData = useMemo(() => klines.map(k => [k.open, k.close, k.low, k.high]), [klines]);
  const volumeData = useMemo(() => klines.map(k => k.volume), [klines]);

  // BOS/ChoCH markers
  const markPoints = useMemo(() => {
    const points: any[] = [];
    for (const s of signals) {
      const idx = dates.indexOf(s.time);
      if (idx < 0) continue;
      const isUp = s.direction === "bullish";
      points.push({
        name: `${s.type} ${s.direction}`,
        coord: [idx, s.price],
        value: s.type,
        symbol: isUp ? "triangle" : "pin",
        symbolSize: 12,
        symbolRotate: isUp ? 0 : 180,
        itemStyle: { color: isUp ? "#22c55e" : "#ef4444" },
        label: {
          show: true,
          formatter: s.type,
          fontSize: 9,
          color: isUp ? "#22c55e" : "#ef4444",
          position: isUp ? "bottom" : "top",
        },
      });
    }
    return points;
  }, [signals, dates]);

  // Sweep markers
  const sweepPoints = useMemo(() => {
    return sweeps.map(s => {
      const idx = dates.indexOf(s.time);
      const isUp = s.direction === "bullish";
      return {
        coord: [idx, s.price],
        symbol: "diamond",
        symbolSize: 8,
        itemStyle: { color: isUp ? "#3b82f6" : "#f97316" },
        label: { show: false },
      };
    });
  }, [sweeps, dates]);

  // FVG zones (markArea)
  const fvgAreas = useMemo(() => {
    return fvg_zones.map(z => {
      const idx = dates.indexOf(z.time);
      if (idx < 0) return null;
      const isBull = z.type === "bullish";
      return [{
        name: "FVG",
        xAxis: idx,
        yAxis: z.bottom,
      }, {
        xAxis: Math.min(idx + 2, dates.length - 1),
        yAxis: z.top,
        itemStyle: {
          color: isBull ? "rgba(59,130,246,0.15)" : "rgba(249,115,22,0.15)",
          borderColor: isBull ? "#3b82f6" : "#f97316",
          borderWidth: 1,
        },
      }];
    }).filter(Boolean);
  }, [fvg_zones, dates]);

  // OB zones (markArea)
  const obAreas = useMemo(() => {
    return ob_zones.map(z => {
      const startIdx = dates.indexOf(z.start);
      const endIdx = dates.indexOf(z.end);
      if (startIdx < 0) return null;
      return [{
        name: "OB",
        xAxis: startIdx,
        yAxis: z.bottom,
      }, {
        xAxis: endIdx >= 0 ? endIdx : dates.length - 1,
        yAxis: z.top,
        itemStyle: {
          color: "rgba(168,85,247,0.12)",
          borderColor: "#a855f7",
          borderWidth: 1,
          borderType: "dashed" as const,
        },
      }];
    }).filter(Boolean);
  }, [ob_zones, dates]);

  // OTE zones (markArea)
  const oteAreas = useMemo(() => {
    return ote_zones.map(z => {
      const startIdx = dates.indexOf(z.start);
      const endIdx = dates.indexOf(z.end);
      if (startIdx < 0) return null;
      return [{
        name: "OTE",
        xAxis: startIdx,
        yAxis: z.bottom,
      }, {
        xAxis: endIdx >= 0 ? endIdx : dates.length - 1,
        yAxis: z.top,
        itemStyle: {
          color: "rgba(245,158,11,0.10)",
          borderColor: "#f59e0b",
          borderWidth: 1,
          borderType: "dotted" as const,
        },
      }];
    }).filter(Boolean);
  }, [ote_zones, dates]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current);
    }
    const chart = chartRef.current;

    const allAreas = [...(fvgAreas || []), ...(obAreas || []), ...(oteAreas || [])];

    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
      },
      grid: [
        { left: 50, right: 20, top: 20, height: "65%" },
        { left: 50, right: 20, top: "78%", height: "15%" },
      ],
      xAxis: [
        { type: "category", data: dates, gridIndex: 0, axisLabel: { show: false } },
        { type: "category", data: dates, gridIndex: 1 },
      ],
      yAxis: [
        { type: "value", gridIndex: 0, scale: true, splitLine: { lineStyle: { color: dark ? "#333" : "#eee" } } },
        { type: "value", gridIndex: 1, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 60, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], bottom: 5, height: 20 },
      ],
      series: [
        {
          type: "candlestick",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: candleData,
          markPoint: {
            data: [...markPoints, ...sweepPoints],
          },
          markArea: {
            silent: true,
            data: allAreas,
          },
        },
        {
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeData,
          itemStyle: {
            color: (_params: any) => {
              const idx = _params.dataIndex;
              if (idx > 0) {
                return klines[idx].close >= klines[idx].open ? "#22c55e" : "#ef4444";
              }
              return "#999";
            },
          },
        },
      ],
    }, true);

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, [dates, candleData, volumeData, markPoints, sweepPoints, fvgAreas, obAreas, oteAreas, dark]);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}

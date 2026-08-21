import { useEffect, useMemo, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";

export interface CzscKline {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CzscBi {
  sdt: string;       // 笔起始日期
  edt: string;       // 笔结束日期
  direction: "up" | "down" | "";
  high: number;
  low: number;
  power?: number;
}

export interface CzscZS {
  sdt: string;       // 中枢起始
  edt: string;       // 中枢结束
  zgg: number;       // 中枢高（上沿）
  zdd: number;       // 中枢低（下沿）
  zgz?: number;      // 上轨
  zdz?: number;      // 下轨
}

export interface CzscBuyPoint {
  date: string;      // 买点所在日期
  type: "一买" | "二买" | "三买" | "一卖" | "二卖" | "三卖" | string;
  price: number;
  live?: boolean;    // true=当前可操作点(高亮), false=历史结构(弱化); 缺省按 true 处理(兼容旧数据)
}

export interface CzscChartProps {
  klines: CzscKline[];
  bis?: CzscBi[];
  zsList?: CzscZS[];
  buyPoints?: CzscBuyPoint[];
  height?: number;
}

export function CzscChart({
  klines,
  bis = [],
  zsList = [],
  buyPoints = [],
  height = 420,
}: CzscChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const { dark } = useDarkMode();

  const dates = useMemo(() => klines.map((k) => k.time), [klines]);
  const candleData = useMemo(
    () => klines.map((k) => [k.open, k.close, k.low, k.high]),
    [klines],
  );
  const volumeData = useMemo(() => klines.map((k) => k.volume), [klines]);

  // 1) 笔折线 (BI): 每一笔是一条 markLine
  //    向上笔：低点→高点；向下笔：高点→低点
  const biMarkLines = useMemo(() => {
    const lines: any[] = [];
    for (const b of bis) {
      const sIdx = dates.indexOf(b.sdt);
      const eIdx = dates.indexOf(b.edt);
      if (sIdx < 0 || eIdx < 0 || sIdx === eIdx) continue;
      const up = b.direction === "up";
      const startPrice = up ? b.low : b.high;
      const endPrice = up ? b.high : b.low;
      lines.push([
        {
          coord: [sIdx, startPrice],
          lineStyle: {
            color: up ? "#16a34a" : "#dc2626",
            width: 1.8,
            type: "solid",
          },
        },
        {
          coord: [eIdx, endPrice],
          lineStyle: {
            color: up ? "#16a34a" : "#dc2626",
            width: 1.8,
            type: "solid",
          },
          label: {
            show: true,
            formatter: up ? "笔↑" : "笔↓",
            fontSize: 9,
            color: up ? "#16a34a" : "#dc2626",
            position: "insideEndTop",
          },
        },
      ]);
    }
    return lines;
  }, [bis, dates]);

  // 2) 中枢矩形 (ZS): 每一个中枢用 markArea 画出区间
  const zsMarkAreas = useMemo(() => {
    const areas: any[] = [];
    for (const z of zsList) {
      const sIdx = dates.indexOf(z.sdt);
      const eIdx = dates.indexOf(z.edt);
      if (sIdx < 0) continue;
      const endIdx = eIdx >= 0 ? eIdx : dates.length - 1;
      if (endIdx <= sIdx) continue;
      if (z.zgg <= 0 || z.zdd <= 0) continue;
      areas.push([
        {
          xAxis: sIdx,
          yAxis: z.zdd,
          itemStyle: {
            color: "rgba(99,102,241,0.12)",
            borderColor: "#6366f1",
            borderWidth: 1,
            borderDash: [4, 4],
          },
        },
        {
          xAxis: endIdx,
          yAxis: z.zgg,
          itemStyle: {
            color: "rgba(99,102,241,0.12)",
            borderColor: "#6366f1",
            borderWidth: 1,
            borderDash: [4, 4],
          },
        },
      ]);
      // 额外加上中枢文字标签（靠左上角）
      areas.push([
        {
          xAxis: sIdx,
          yAxis: z.zgg,
          label: {
            show: true,
            position: "insideTopLeft",
            formatter: `中枢 ZS [${z.zdd.toFixed(2)}~${z.zgg.toFixed(2)}]`,
            color: "#6366f1",
            fontSize: 10,
          },
        },
        { xAxis: endIdx, yAxis: z.zgg },
      ]);
    }
    return areas;
  }, [zsList, dates]);

  // 3) 买点 / 卖点 标记点
  //    live=true 当前可操作点(高亮实心); live=false 历史结构(弱化半透明)
  const buySellMarkPoints = useMemo(() => {
    const pts: any[] = [];
    for (const bp of buyPoints) {
      const idx = dates.indexOf(bp.date);
      if (idx < 0) continue;
      const isBuy = !/卖|空|short|bear/i.test(bp.type);
      const live = bp.live !== false; // 缺省视为高亮(兼容旧数据)
      const baseColor = isBuy ? "#16a34a" : "#dc2626";
      const mutedColor = isBuy ? "#86c98a" : "#f0a3a3";
      pts.push({
        name: bp.type,
        coord: [idx, bp.price],
        value: bp.type,
        symbol: isBuy ? "triangle" : "pin",
        symbolSize: live ? 16 : 10,
        symbolRotate: isBuy ? 0 : 180,
        itemStyle: {
          color: live ? baseColor : mutedColor,
          opacity: live ? 1 : 0.5,
          borderColor: "#fff",
          borderWidth: 1,
        },
        label: {
          show: true,
          formatter: bp.type,
          fontSize: live ? 11 : 10,
          fontWeight: live ? ("bold" as const) : ("normal" as const),
          color: live ? baseColor : mutedColor,
          position: isBuy ? "bottom" : "top",
        },
      });
    }
    return pts;
  }, [buyPoints, dates]);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current);
    }
    const chart = chartRef.current;

    chart.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross" },
        },
        legend: {
          data: ["K线", "笔", "中枢", "买卖点"],
          top: 0,
          right: 10,
          textStyle: { color: dark ? "#ccc" : "#444", fontSize: 11 },
        },
        grid: [
          { left: 60, right: 20, top: 36, height: "60%" },
          { left: 60, right: 20, top: "76%", height: "14%" },
        ],
        xAxis: [
          { type: "category", data: dates, gridIndex: 0, axisLabel: { show: false } },
          {
            type: "category",
            data: dates,
            gridIndex: 1,
            axisLabel: {
              color: dark ? "#aaa" : "#555",
              fontSize: 10,
              hideOverlap: true,
            },
          },
        ],
        yAxis: [
          {
            type: "value",
            gridIndex: 0,
            scale: true,
            splitLine: { lineStyle: { color: dark ? "#2a2a2a" : "#ececec" } },
            axisLabel: { color: dark ? "#aaa" : "#555", fontSize: 10 },
          },
          {
            type: "value",
            gridIndex: 1,
            splitLine: { show: false },
            axisLabel: { show: false },
          },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1], start: 50, end: 100 },
          { type: "slider", xAxisIndex: [0, 1], bottom: 2, height: 18 },
        ],
        series: [
          {
            name: "K线",
            type: "candlestick",
            xAxisIndex: 0,
            yAxisIndex: 0,
            data: candleData,
            itemStyle: {
              color: "#ef4444",
              color0: "#22c55e",
              borderColor: "#ef4444",
              borderColor0: "#22c55e",
            },
            markLine: {
              silent: true,
              symbol: "none",
              data: biMarkLines as any,
            },
            markPoint: {
              data: buySellMarkPoints,
              symbol: "triangle",
            },
            markArea: {
              silent: true,
              data: zsMarkAreas as any,
            },
          },
          {
            name: "成交量",
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: volumeData,
            itemStyle: {
              color: (p: any) => {
                const i = p.dataIndex;
                if (i > 0) {
                  return klines[i].close >= klines[i].open ? "#ef4444" : "#22c55e";
                }
                return "#9ca3af";
              },
            },
          },
        ],
      },
      true,
    );

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [
    dates,
    candleData,
    volumeData,
    biMarkLines,
    zsMarkAreas,
    buySellMarkPoints,
    dark,
    klines,
  ]);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}

import { useEffect, useRef } from "react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useDarkMode } from "@/hooks/useDarkMode";

interface IntradayBar {
  t: string;
  p: number;
  v: number;
}

interface Props {
  bars: IntradayBar[];
  prevClose: number | null;
  height?: number;
}

export function IntradayChart({ bars, prevClose, height = 280 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const { dark } = useDarkMode();

  useEffect(() => {
    if (!ref.current || bars.length < 2) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current);
    }
    const chart = chartRef.current;
    const theme = getChartTheme();

    const times = bars.map(b => b.t);
    const prices = bars.map(b => b.p);
    const volumes = bars.map(b => b.v);
    const pc = prevClose ?? prices[0];

    const priceGridH = "68%";
    const volGridH = "18%";
    const gap = "6%";

    const priceOpt = {
      type: "line",
      data: prices,
      smooth: true,
      symbol: "none",
      lineStyle: { width: 1.5, color: theme.infoColor },
      areaStyle: {
        color: {
          type: "linear",
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: theme.infoColor + "55" },
            { offset: 1, color: theme.infoColor + "08" },
          ],
        },
      },
      markLine: pc > 0 ? {
        silent: true,
        symbol: "none",
        lineStyle: { color: theme.textColor, type: "dashed", width: 1 },
        label: { show: false },
        data: [{ yAxis: pc }],
      } : undefined,
      z: 2,
    };

    const volColors = volumes.map(v =>
      v > 0 && prices[volumes.indexOf(v)] >= pc ? theme.volumeUp : theme.volumeDown
    );

    const option = {
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: any[]) => {
          if (!params.length) return "";
          const p = params[0];
          return `<div style="font-size:12px;font-weight:500;margin-bottom:4px">${p.axisValue}</div>` +
            `<div>价格: <b>${p.value.toFixed(2)}</b></div>` +
            (pc > 0 ? `<div style="color:${p.value >= pc ? theme.upColor : theme.downColor}">涨跌: ${(p.value - pc) >= 0 ? "+" : ""}${(p.value - pc).toFixed(2)} (${((p.value - pc) / pc * 100).toFixed(2)}%)</div>` : "") +
            (params[1] ? `<div>成交量: ${(params[1].value / 10000).toFixed(1)}万</div>` : "");
        },
      },
      grid: [
        { left: 60, right: 20, top: 16, height: priceGridH },
        { left: 60, right: 20, top: `${+parseFloat(priceGridH) + +parseFloat(gap)}%`, height: volGridH },
      ],
      xAxis: [
        {
          type: "category",
          data: times,
          boundaryGap: false,
          axisLine: { lineStyle: { color: theme.axisColor } },
          axisLabel: {
            color: theme.textColor, fontSize: 10,
            formatter: (v: string) => {
              const hour = parseInt(v.split(":")[0]);
              if (hour === 11) return "11:30";
              if (hour === 13) return "13:00";
              if (v.endsWith(":00") || v.endsWith(":30")) return v;
              return "";
            },
            interval: 59,
          },
          axisTick: { show: false },
          gridIndex: 0,
        },
        {
          type: "category",
          data: times,
          boundaryGap: false,
          axisLine: { show: false },
          axisLabel: { show: false },
          axisTick: { show: false },
          gridIndex: 1,
        },
      ],
      yAxis: [
        {
          type: "value",
          scale: true,
          splitLine: { lineStyle: { color: theme.gridColor, type: "dashed" } },
          axisLabel: { color: theme.textColor, fontSize: 10 },
          gridIndex: 0,
          min: (val: any) => Math.min(pc, val.min) * 0.998,
          max: (val: any) => Math.max(pc, val.max) * 1.002,
        },
        {
          type: "value",
          splitLine: { show: false },
          axisLabel: { show: false },
          gridIndex: 1,
        },
      ],
      series: [
        { ...priceOpt, xAxisIndex: 0, yAxisIndex: 0 },
        {
          type: "bar",
          data: volumes,
          itemStyle: { color: (p: any) => volColors[p.dataIndex] },
          barWidth: "60%",
          xAxisIndex: 1,
          yAxisIndex: 1,
          z: 1,
        },
      ],
    };

    chart.setOption(option, true);

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [bars, prevClose, dark]);

  if (bars.length < 2) {
    return (
      <div style={{ height }} className="flex items-center justify-center text-sm text-muted-foreground">
        暂无分时数据
      </div>
    );
  }

  return <div ref={ref} style={{ height, width: "100%" }} />;
}

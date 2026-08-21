import { useState, useCallback, useRef } from "react";
export type DrawingType = "hline" | "vline" | "trend" | "erase" | "none";

export interface HLineDrawing {
  id: string;
  type: "hline";
  yValue: number;
  label: string;
  color: string;
}

export interface VLineDrawing {
  id: string;
  type: "vline";
  xIndex: number;
  label: string;
  color: string;
}

export interface TrendLineDrawing {
  id: string;
  type: "trend";
  coords: [number, number][];
  label: string;
  color: string;
}

export type LineDrawing = HLineDrawing | VLineDrawing | TrendLineDrawing;

const COLORS = ["#ef4444", "#22c55e", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4"];

export function useDrawing() {
  const drawingsRef = useRef<LineDrawing[]>([]);
  const [drawings, setDrawings] = useState<LineDrawing[]>([]);
  const [tool, setTool] = useState<DrawingType>("none");
  const colorIdx = useRef(0);

  const nextColor = useCallback(() => {
    const c = COLORS[colorIdx.current % COLORS.length];
    colorIdx.current += 1;
    return c;
  }, []);

  const addHLine = useCallback(
    (yValue: number, label?: string) => {
      const d: HLineDrawing = {
        id: `hl_${Date.now()}`,
        type: "hline",
        yValue,
        label: label || `H ${yValue.toFixed(2)}`,
        color: nextColor(),
      };
      drawingsRef.current = [...drawingsRef.current, d];
      setDrawings([...drawingsRef.current]);
      return d;
    },
    [nextColor],
  );

  const addVLine = useCallback(
    (xIndex: number, label?: string) => {
      const d: VLineDrawing = {
        id: `vl_${Date.now()}`,
        type: "vline",
        xIndex,
        label: label || `V ${xIndex}`,
        color: nextColor(),
      };
      drawingsRef.current = [...drawingsRef.current, d];
      setDrawings([...drawingsRef.current]);
      return d;
    },
    [nextColor],
  );

  const removeDrawing = useCallback((id: string) => {
    drawingsRef.current = drawingsRef.current.filter((d) => d.id !== id);
    setDrawings([...drawingsRef.current]);
  }, []);

  const clearAll = useCallback(() => {
    drawingsRef.current = [];
    setDrawings([]);
  }, []);

  return { drawings, setDrawings, tool, setTool, addHLine, addVLine, removeDrawing, clearAll };
}

interface ChartDrawingToolbarProps {
  tool: DrawingType;
  onSetTool: (t: DrawingType) => void;
  drawingsCount: number;
  onClear: () => void;
}

export function ChartDrawingToolbar({ tool, onSetTool, drawingsCount, onClear }: ChartDrawingToolbarProps) {
  const tools: { id: DrawingType; label: string; shortcut: string }[] = [
    { id: "none", label: "Select", shortcut: "V" },
    { id: "hline", label: "H-Line", shortcut: "H" },
    { id: "vline", label: "V-Line", shortcut: "L" },
    { id: "trend", label: "Trend", shortcut: "T" },
    { id: "erase", label: "Erase", shortcut: "E" },
  ];

  return (
    <div className="flex items-center gap-1 p-1 bg-background/90 backdrop-blur rounded-lg border shadow-sm">
      {tools.map((t) => (
        <button
          key={t.id}
          onClick={() => onSetTool(t.id)}
          className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors ${tool === t.id ? "bg-primary/15 text-primary font-medium" : "text-muted-foreground/50 hover:text-muted-foreground"}`}
          title={`${t.label} (${t.shortcut})`}
        >
          {t.label}
        </button>
      ))}
      <div className="w-px h-4 bg-border/40 mx-1" />
      <button onClick={onClear} disabled={drawingsCount === 0} className="px-2 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-30">
        Clear
      </button>
      {drawingsCount > 0 && <span className="text-[10px] text-muted-foreground px-1">{drawingsCount}</span>}
    </div>
  );
}
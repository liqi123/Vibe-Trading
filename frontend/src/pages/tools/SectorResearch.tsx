import { useMemo, useState } from "react";
import {
  ArrowLeft, Bot, BatteryCharging, BatteryFull, BrainCircuit, Cable, Car, CircuitBoard, Copy, Cpu,
  Database, Dna, Atom, Glasses, Microchip, MemoryStick, Pill, Pickaxe, Plane, Rocket, Shield,
  UtilityPole, Flame, Check,
} from "lucide-react";
import { SECTORS, sectorSteps, type SectorBrief } from "@/lib/sectorResearch";
import { cn } from "@/lib/utils";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Bot, Cpu, MemoryStick, Cable, CircuitBoard, Microchip, BatteryFull, Plane, Car, Pill,
  UtilityPole, Shield, Atom, Rocket, Dna, Pickaxe, BrainCircuit, Glasses, BatteryCharging, Database,
};

export function SectorResearch() {
  const [sel, setSel] = useState<SectorBrief | null>(null);
  const [copied, setCopied] = useState<number | null>(null);

  const steps = useMemo(() => (sel ? sectorSteps(sel) : []), [sel]);

  const copy = async (n: number, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(n);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* 剪贴板不可用时静默 */
    }
  };

  if (sel) {
    const Icon = ICONS[sel.icon] ?? Bot;
    return (
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <button onClick={() => setSel(null)} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> 返回板块列表
        </button>
        <div className="flex items-center gap-3">
          <Icon className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-xl font-bold">{sel.label}</h1>
            <p className="text-sm text-muted-foreground">{sel.tagline}</p>
          </div>
        </div>
        <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
          分 {steps.length} 步：第 1 步读研报整理要点，之后每步产出一页笔记。
          复制提示词发给你常用的 AI，按顺序执行；内容由 AI 当场查资料产出，本页不预填任何结论。
          {sel.verified && sel.nodes.length ? ` 已核实环节：${sel.nodes.join("、")}。` : ""}
        </div>
        <div className="space-y-3">
          {steps.map((s) => (
            <div key={s.n} className="rounded-lg border">
              <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
                <span className="text-sm font-semibold">
                  第 {s.n} 步 · {s.title}
                </span>
                <button
                  onClick={() => copy(s.n, s.prompt)}
                  className="flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-muted"
                >
                  {copied === s.n ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
                  {copied === s.n ? "已复制" : "复制"}
                </button>
              </div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed">{s.prompt}</pre>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <Flame className="h-5 w-5 text-primary" /> 产业研究 · 20 个板块
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          每个板块配一组分步研究提示词：先读研报，再逐页梳理技术路线、产业链与格局。
          复制到你常用的 AI 使用；内容由 AI 当场查资料产出，每个数字要求注明来源与年份。
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SECTORS.map((s) => {
          const Icon = ICONS[s.icon] ?? Bot;
          return (
            <button
              key={s.key}
              onClick={() => setSel(s)}
              className={cn(
                "rounded-lg border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-muted/40",
              )}
            >
              <div className="flex items-center gap-2.5">
                <Icon className="h-6 w-6 shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 font-semibold">
                    {s.label}
                    {s.hot && <span className="rounded bg-danger/10 px-1 text-[10px] font-medium text-danger">热</span>}
                    {s.verified && <span className="rounded bg-success/10 px-1 text-[10px] font-medium text-success">已核实</span>}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">{s.tagline}</p>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {sectorSteps(s).length} 步提示词
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

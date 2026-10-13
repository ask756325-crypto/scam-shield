"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateTime } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

// Validated with the dataviz palette validator (CVD + normal-vision separation, chroma, contrast).
export const CHANGE_COLORS = { new: "#138a76", changed: "#d08a1e", resolved: "#6a5acd" };
// Severity is ordinal → single-hue sequential ramp; the level name is always printed beside the bar.
export const SEVERITY_RAMP: Record<string, string> = { critical: "#7d2416", high: "#a8432c", medium: "#cc7d63", low: "#e2b8a9" };

const axis = { fontSize: 11, fill: "var(--color-ink-500)" };

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string; payload: { at: string; mode: string } }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-ink-150 bg-paper px-3 py-2 text-[12px] shadow-pop">
      <div className="mb-1 font-medium text-ink-900">
        Scan #{label} <span className="font-normal text-ink-500">· {dateTime(p.at)}{p.mode === "demo" ? " · synthetic" : ""}</span>
      </div>
      {payload.map((x) => (
        <div key={x.name} className="flex items-center gap-2 text-ink-700">
          <span className="size-2 rounded-[2px]" style={{ background: x.color }} />
          <span className="flex-1">{x.name}</span>
          <span className="tabular font-medium text-ink-900">{x.value}</span>
        </div>
      ))}
    </div>
  );
}

export function CandidatesChart({ series }: { series: Dashboard["scan_series"] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={series} margin={{ top: 8, right: 4, left: -18, bottom: 0 }} barCategoryGap="28%">
        <CartesianGrid vertical={false} stroke="var(--color-ink-100)" />
        <XAxis dataKey="scan_id" tick={axis} tickLine={false} axisLine={{ stroke: "var(--color-ink-150)" }} tickFormatter={(v) => `#${v}`} />
        <YAxis tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--color-ink-100)", opacity: 0.6 }} />
        <Bar dataKey="candidates" name="Unique candidates" fill="#3b7c73" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ChangesChart({ series }: { series: Dashboard["scan_series"] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={series} margin={{ top: 8, right: 4, left: -18, bottom: 0 }} barCategoryGap="22%" barGap={2}>
        <CartesianGrid vertical={false} stroke="var(--color-ink-100)" />
        <XAxis dataKey="scan_id" tick={axis} tickLine={false} axisLine={{ stroke: "var(--color-ink-150)" }} tickFormatter={(v) => `#${v}`} />
        <YAxis tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--color-ink-100)", opacity: 0.6 }} />
        <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11.5, color: "var(--color-ink-600)", paddingTop: 4 }} />
        <Bar dataKey="new" name="New" fill={CHANGE_COLORS.new} radius={[3, 3, 0, 0]} maxBarSize={12} />
        <Bar dataKey="changed" name="Changed" fill={CHANGE_COLORS.changed} radius={[3, 3, 0, 0]} maxBarSize={12} />
        <Bar dataKey="resolved" name="Not seen again" fill={CHANGE_COLORS.resolved} radius={[3, 3, 0, 0]} maxBarSize={12} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SeverityRows({ severity, onSelect }: { severity: Dashboard["severity"]; onSelect?: (level: string) => void }) {
  const max = Math.max(1, ...Object.values(severity));
  const labels: Record<string, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
  return (
    <ul className="space-y-2.5">
      {(["critical", "high", "medium", "low"] as const).map((lvl) => (
        <li key={lvl}>
          <button onClick={() => onSelect?.(lvl)} className="group grid w-full grid-cols-[70px_1fr_36px] items-center gap-3 text-left" title={`${severity[lvl]} open ${labels[lvl].toLowerCase()} findings`}>
            <span className="text-[12.5px] text-ink-700 group-hover:text-ink-950">{labels[lvl]}</span>
            <span className="h-2 overflow-hidden rounded-full bg-ink-100">
              <span className="block h-full rounded-full transition-[width] duration-500" style={{ width: `${(severity[lvl] / max) * 100}%`, background: SEVERITY_RAMP[lvl] }} />
            </span>
            <span className="tabular text-right text-[13px] font-medium text-ink-900">{severity[lvl]}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

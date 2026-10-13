"use client";

import { AppWindow, AtSign, Beaker, FileUp, Smartphone } from "lucide-react";
import { useState } from "react";
import { avatarSrc, sourceLabel } from "@/lib/format";
import type { ChangeState, FindingStatus, RiskLevel } from "@/lib/types";
import { Badge, cx } from "../ui";

const RISK: Record<RiskLevel, { tone: "crit" | "high" | "med" | "low" | "neutral"; label: string }> = {
  critical: { tone: "crit", label: "Critical" },
  high: { tone: "high", label: "High" },
  medium: { tone: "med", label: "Medium" },
  low: { tone: "low", label: "Low" },
  info: { tone: "neutral", label: "Info" },
};

export const RISK_COLORS: Record<string, string> = {
  critical: "var(--color-crit)",
  high: "var(--color-high)",
  medium: "var(--color-med)",
  low: "var(--color-low)",
};

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  const r = RISK[level] ?? RISK.info;
  return (
    <Badge tone={r.tone} dot>
      {r.label}
      {score !== undefined && <span className="tabular opacity-70">· {Math.round(score)}</span>}
    </Badge>
  );
}

export function StatusBadge({ status, level }: { status: FindingStatus; level?: RiskLevel }) {
  if (status === "open" && level === "info")
    return (
      <Badge tone="neutral" title="Re-scored below the brand relevance threshold; kept for history">
        Below threshold
      </Badge>
    );
  const map: Record<FindingStatus, { tone: "dark" | "forest" | "outline" | "teal"; label: string }> = {
    open: { tone: "outline", label: level === "low" ? "Open" : "Needs review" },
    escalated: { tone: "teal", label: "Further review" },
    confirmed: { tone: "dark", label: "Confirmed" },
    safe: { tone: "forest", label: "Marked legitimate" },
    resolved: { tone: "teal", label: "No longer observed" },
  };
  const m = map[status] ?? map.open;
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

export function ChangeBadge({ state }: { state: ChangeState }) {
  const map: Record<ChangeState, { tone: "teal" | "high" | "neutral" | "forest"; label: string; title: string }> = {
    new: { tone: "teal", label: "New", title: "First observed in the most recent scan that saw it" },
    changed: { tone: "high", label: "Changed", title: "Profile/listing content or risk level changed since the previous observation" },
    recurring: { tone: "neutral", label: "Recurring", title: "Observed again without material changes" },
    missing: { tone: "neutral", label: "Missing", title: "Not returned by the latest clean scan of its source; resolved only if it stays missing" },
    resolved: { tone: "forest", label: "No longer observed", title: "Absent from consecutive clean scans of its source" },
  };
  const m = map[state] ?? map.recurring;
  return (
    <Badge tone={m.tone} title={m.title}>
      {m.label}
    </Badge>
  );
}

export function SourceTypeBadge({ type }: { type: "live" | "simulated" | "imported" | string }) {
  if (type === "simulated")
    return (
      <Badge tone="med" title="Synthetic demo record — not real-world data">
        <Beaker className="size-3" /> Simulated
      </Badge>
    );
  if (type === "imported")
    return (
      <Badge tone="outline" title="Imported by an analyst from a CSV file">
        <FileUp className="size-3" /> Imported
      </Badge>
    );
  return (
    <Badge tone="forest" title="Collected from a live source">
      <span className="size-1.5 rounded-full bg-forest-500" /> Live
    </Badge>
  );
}

/** Small monochrome platform glyphs (not official brand logos). */
export function PlatformGlyph({ platform, className }: { platform: string; className?: string }) {
  const c = cx("size-3.5 shrink-0", className);
  if (platform === "bluesky")
    return (
      <svg viewBox="0 0 24 24" className={c} aria-hidden>
        <path fill="currentColor" d="M6.3 4.2C8.6 5.9 11 9.4 12 11.4c1-2 3.4-5.5 5.7-7.2 1.6-1.2 4.3-2.2 4.3.9 0 .6-.4 5.2-.6 5.9-.7 2.6-3.3 3.2-5.6 2.8 4 .7 5 3 2.8 5.2-4.2 4.3-6-1.1-6.5-2.5l-.1-.4-.1.4c-.5 1.4-2.3 6.8-6.5 2.5-2.2-2.2-1.2-4.5 2.8-5.2-2.3.4-4.9-.2-5.6-2.8C2.4 10.3 2 5.7 2 5.1c0-3.1 2.7-2.1 4.3-.9Z" />
      </svg>
    );
  if (platform === "mastodon") return <AtSign className={c} aria-hidden />;
  if (platform === "apple" || platform === "apple_app_store") return <Smartphone className={c} aria-hidden />;
  if (platform === "google_play") return <AppWindow className={c} aria-hidden />;
  return <AtSign className={c} aria-hidden />;
}

export function PlatformLabel({ platform }: { platform: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-600">
      <PlatformGlyph platform={platform} className="text-ink-500" />
      {sourceLabel(platform)}
    </span>
  );
}

export function Avatar({ url, name, size = 32, square }: { url?: string | null; name: string; size?: number; square?: boolean }) {
  const [failed, setFailed] = useState(false);
  const src = avatarSrc(url);
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <span
      className={cx("relative inline-grid shrink-0 place-items-center overflow-hidden border border-ink-150 bg-ink-100 text-[11px] font-semibold text-ink-500", square ? "rounded-[22%]" : "rounded-full")}
      style={{ width: size, height: size }}
    >
      {src && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" width={size} height={size} referrerPolicy="no-referrer" loading="lazy" onError={() => setFailed(true)} className="size-full object-cover" />
      ) : (
        initials || "?"
      )}
    </span>
  );
}

export function ScoreMeter({ value, evaluated = true, className }: { value: number; evaluated?: boolean; className?: string }) {
  if (!evaluated) return <span className={cx("text-[11.5px] text-ink-400", className)}>Not evaluated</span>;
  const pctv = Math.round(value * 100);
  const color = value >= 0.75 ? "bg-crit" : value >= 0.5 ? "bg-high" : value >= 0.3 ? "bg-med" : "bg-ink-300";
  return (
    <span className={cx("inline-flex items-center gap-2", className)}>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-100">
        <span className={cx("block h-full rounded-full", color)} style={{ width: `${Math.max(2, pctv)}%` }} />
      </span>
      <span className="tabular w-8 text-right text-[12px] text-ink-700">{pctv}%</span>
    </span>
  );
}

export function StatusDot({ status, className }: { status: string; className?: string }) {
  const color =
    status === "ok" || status === "completed" || status === "empty"
      ? "bg-forest-500"
      : status === "partial" || status === "rate_limited"
        ? "bg-med"
        : status === "failed"
          ? "bg-crit"
          : status === "running" || status === "queued"
            ? "bg-teal-500 animate-pulse-dot"
            : "bg-ink-300";
  return <span className={cx("inline-block size-2 shrink-0 rounded-full", color, className)} aria-hidden />;
}

export const SOURCE_HEALTH_LABEL: Record<string, string> = {
  not_tested: "Not tested",
  operational: "Operational",
  no_results: "Responding · no results",
  degraded: "Partial results",
  rate_limited: "Rate limited",
  failing: "Failing",
  invalid_config: "Invalid configuration",
  simulated: "Synthetic data",
};
export const SOURCE_STATE_LABEL: Record<string, string> = { live: "Live", simulated: "Simulated", disabled: "Disabled", unavailable: "Unavailable" };
/** StatusDot status for a registry entry: disabled grey, unavailable red/amber, untested grey, otherwise green. */
export function sourceDot(s: { enabled: boolean; state?: string; health?: string }) {
  if (!s.enabled || s.state === "disabled") return "off";
  if (s.health === "rate_limited" || s.health === "degraded") return "partial";
  if (s.state === "unavailable") return "failed";
  if (s.health === "not_tested" || s.health === "simulated") return "unknown";
  return "ok";
}

export const SOURCE_STATUS_LABEL: Record<string, string> = {
  ok: "Operational",
  empty: "No results",
  partial: "Partial results",
  failed: "Failing",
  rate_limited: "Rate limited",
  unknown: "Not checked yet",
  running: "Running",
  pending: "Pending",
  skipped: "Skipped",
};

"use client";

import clsx from "clsx";
import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { PlatformGlyph } from "../app/bits";
import { IllustrativeTag } from "./previews";

// Illustrative data: the fictional demo brand "Northvale Pay".
const OFFICIAL = [
  { platform: "bluesky", id: "@northvalepay.example" },
  { platform: "apple", id: "com.northvale.pay" },
  { platform: "google_play", id: "com.northvale.pay" },
];

const CANDIDATES = [
  { name: "N0rthvale Pay", where: "Bluesky", platform: "bluesky", signals: ["homoglyph", "logo 97%", "giveaway"], level: "Critical", tone: "crit" },
  { name: "Northvale Pay – Wallet Login", where: "Google Play", platform: "google_play", signals: ["publisher ≠ official", "look-alike URL"], level: "Critical", tone: "crit" },
  { name: "NorthvaIe Pay", where: "App Store", platform: "apple", signals: ["capital-I swap", "copied description"], level: "High", tone: "high" },
  { name: "Northvale Hiking Club", where: "Mastodon", platform: "mastodon", signals: ["name only"], level: "Low", tone: "low" },
] as const;

const TONE: Record<string, string> = {
  crit: "border-[#a8321f]/50 bg-[#a8321f]/15 text-[#f2a08f]",
  high: "border-[#b8580f]/50 bg-[#b8580f]/15 text-[#f0b98a]",
  low: "border-ink-600 bg-ink-800 text-ink-300",
};

export function HeroPreview() {
  // step = number of candidates scored so far; loops with a pause at the end.
  const [step, setStep] = useState<number>(CANDIDATES.length);
  const [animate, setAnimate] = useState(false);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setAnimate(true);
    setStep(0);
    const id = setInterval(() => setStep((s) => (s >= CANDIDATES.length + 3 ? 0 : s + 1)), 1100);
    return () => clearInterval(id);
  }, []);
  const scored = Math.min(step, CANDIDATES.length);
  const progress = scored / CANDIDATES.length;

  return (
    <figure className="overflow-hidden rounded-xl border border-white/10 bg-ink-900/80 shadow-[0_50px_100px_-40px_rgba(0,0,0,0.75)] backdrop-blur-sm" aria-label="Illustration: a scan of the fictional brand Northvale Pay showing excluded official assets and scored look-alike candidates">
      <figcaption className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-2.5">
        <span className="flex items-center gap-2 text-[12px] text-ink-300">
          <span className={clsx("size-1.5 rounded-full", scored < CANDIDATES.length ? "bg-teal-400 animate-pulse-dot" : "bg-forest-500")} aria-hidden />
          {scored < CANDIDATES.length ? "Scanning" : "Scan complete"} · <span className="text-ink-100">Northvale Pay</span>
        </span>
        <IllustrativeTag dark />
      </figcaption>
      <div className="h-px bg-white/5">
        <div className="h-px bg-gradient-to-r from-forest-500 to-teal-400 transition-[width] duration-700 ease-out" style={{ width: `${Math.max(4, progress * 100)}%` }} />
      </div>

      {/* Official assets */}
      <div className="border-b border-white/10 px-4 py-3">
        <div className="mb-2 flex items-center justify-between text-[10.5px] tracking-[0.12em] text-ink-500 uppercase">
          <span>Official assets</span>
          <span className="normal-case tracking-normal">excluded by exact ID</span>
        </div>
        <ul className="flex flex-wrap gap-1.5">
          {OFFICIAL.map((o) => (
            <li key={o.platform} className="inline-flex items-center gap-1.5 rounded-[5px] border border-teal-700/50 bg-teal-700/15 px-2 py-1 font-mono text-[11px] text-teal-200">
              <ShieldCheck className="size-3 text-teal-400" aria-hidden />
              <PlatformGlyph platform={o.platform} className="size-3 text-teal-400" />
              {o.id}
            </li>
          ))}
        </ul>
      </div>

      {/* Candidates */}
      <div className="px-4 pt-3 pb-1 text-[10.5px] tracking-[0.12em] text-ink-500 uppercase">Look-alike candidates</div>
      <ul className="divide-y divide-white/[0.06]">
        {CANDIDATES.map((c, i) => {
          const done = i < scored;
          const active = animate && i === scored;
          return (
            <li key={c.name} className={clsx("flex items-center gap-3 px-4 py-3 transition-colors duration-500", active && "bg-teal-400/[0.04]")}>
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-ink-800 text-ink-400">
                <PlatformGlyph platform={c.platform} className="size-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-ink-100">{c.name}</div>
                <div className={clsx("mt-1 flex flex-wrap gap-1 transition-opacity duration-500", done ? "opacity-100" : "opacity-0")}>
                  {c.signals.map((s) => (
                    <span key={s} className="rounded-[3px] bg-white/[0.06] px-1.5 py-px font-mono text-[10.5px] text-ink-300">{s}</span>
                  ))}
                </div>
              </div>
              <span className={clsx("shrink-0 rounded-[4px] border px-1.5 py-0.5 text-[11px] font-medium transition-opacity duration-500", TONE[c.tone], done ? "opacity-100" : "opacity-0")}>
                {c.level}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="border-t border-white/10 px-4 py-2.5 text-[11.5px] text-ink-500">
        Name similarity alone stays <span className="text-ink-300">Low</span> — every level above needs independent evidence.
      </div>
    </figure>
  );
}

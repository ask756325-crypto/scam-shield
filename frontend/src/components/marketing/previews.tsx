/*
 * Product previews for the landing page. They reuse the application's own badge/meter components, but the
 * data is illustrative: every value describes the fictional demo brand "Northvale Pay" and each preview is
 * labelled as such. Nothing here represents real customers, real accounts or measured detection rates.
 */
import clsx from "clsx";
import { Ban, Check, CircleSlash, FileSearch, Fingerprint, Link2, ShieldCheck, Type } from "lucide-react";
import type { ReactNode } from "react";
import { ChangeBadge, PlatformGlyph, RiskBadge, ScoreMeter, SourceTypeBadge } from "../app/bits";

export function IllustrativeTag({ dark }: { dark?: boolean }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 font-mono text-[10.5px] tracking-wide whitespace-nowrap text-ink-400" title="Illustrative data for the fictional brand Northvale Pay">
      <span className={clsx("size-1.5 rounded-full", dark ? "bg-teal-400" : "bg-teal-500")} aria-hidden />
      Illustrative<span className="hidden sm:inline"> · fictional brand</span>
    </span>
  );
}

export function Frame({ title, children, className, dark }: { title: string; children: ReactNode; className?: string; dark?: boolean }) {
  return (
    <figure
      className={clsx(
        "overflow-hidden rounded-xl border",
        dark ? "border-ink-700 bg-ink-850 shadow-[0_40px_80px_-40px_rgba(0,0,0,0.7)]" : "border-ink-150 bg-paper shadow-[0_30px_60px_-36px_rgba(17,19,18,0.28)]",
        className,
      )}
    >
      <figcaption className={clsx("flex items-center justify-between gap-3 border-b px-4 py-2.5", dark ? "border-ink-700" : "border-ink-150")}>
        <span className={clsx("truncate text-[12px] font-medium", dark ? "text-ink-200" : "text-ink-700")}>{title}</span>
        <IllustrativeTag dark={dark} />
      </figcaption>
      {children}
    </figure>
  );
}

function Initial({ letter, tone = "forest", square }: { letter: string; tone?: "forest" | "ink" | "plum"; square?: boolean }) {
  const t = { forest: "bg-forest-700 text-forest-100", ink: "bg-ink-200 text-ink-700", plum: "bg-[#ddd3e6] text-[#5b4a6b]" }[tone];
  return <span className={clsx("grid size-9 shrink-0 place-items-center text-[13px] font-semibold", square ? "rounded-[22%]" : "rounded-full", t)} aria-hidden>{letter}</span>;
}

// ---------------------------------------------------------------- 2. Social impersonation

export function SocialPreview() {
  const rows: { label: string; icon: typeof Type; value: number; corroborates?: boolean; detail: string }[] = [
    { label: "Name / handle", icon: Type, value: 1, detail: "Homoglyph: “N0rthvale” → “Northvale”" },
    { label: "Avatar vs. logo", icon: Fingerprint, value: 0.97, corroborates: true, detail: "Perceptual hash distance 2 / 64" },
    { label: "Bio & links", icon: Link2, value: 0.58, corroborates: true, detail: "URL shortener; “claim” in path" },
    { label: "Scam language", icon: FileSearch, value: 0.55, corroborates: true, detail: "Crypto giveaway wording" },
  ];
  return (
    <Frame title="Social Monitoring · candidate account">
      <div className="p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <Initial letter="N" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[14px] font-semibold text-ink-950">N0rthvale Pay</span>
              <ChangeBadge state="new" />
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-500">
              <PlatformGlyph platform="bluesky" /> @n0rthvalepay.bsky.social
            </div>
          </div>
          <RiskBadge level="critical" score={73} />
        </div>
        <p className="mt-3 rounded-md border border-ink-150 bg-white px-3 py-2 text-[12.5px] leading-relaxed text-ink-700">
          Northvale Pay anniversary <mark className="rounded-[3px] bg-crit-bg px-0.5 text-crit">giveaway</mark>! Send 0.1 ETH and receive 0.2 back.{" "}
          <mark className="rounded-[3px] bg-high-bg px-0.5 text-high">bit.ly/nv-claim</mark>
        </p>
        <ul className="mt-4 divide-y divide-ink-150 border-y border-ink-150">
          {rows.map(({ label, icon: Icon, value, corroborates, detail }) => (
            <li key={label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 py-2.5">
              <span className="flex items-center gap-2 text-[12.5px] font-medium text-ink-800">
                <Icon className="size-3.5 text-ink-400" aria-hidden />
                {label}
                {corroborates && (
                  <span className="inline-flex items-center gap-0.5 text-[11px] font-normal text-forest-600">
                    <Check className="size-3" aria-hidden /> corroborates
                  </span>
                )}
              </span>
              <ScoreMeter value={value} />
              <span className="col-span-2 pl-5.5 text-[11.5px] text-ink-500">{detail}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[12px] text-ink-600">
          <span className="font-medium text-ink-900">Potential impersonation with scam indicators — review required.</span>
        </p>
      </div>
    </Frame>
  );
}

// ---------------------------------------------------------------- 3. Suspicious apps

const APP_ROWS = [
  { name: "Northvale Pay", id: "com.northvale.pay", letter: "N", tone: "forest" as const, publisher: "1550000000", publisherNote: null, icon: null, outcome: "official" as const },
  { name: "Northvale Pay – Wallet Login", id: "com.nvpay.wallet.login", letter: "N", tone: "forest" as const, publisher: "8812773", publisherNote: "Not an official publisher", icon: 0.75, outcome: { level: "critical" as const, score: 78 } },
  { name: "Bill Split Calculator for Northvale", id: "com.utilitylabs.splitcalc", letter: "B", tone: "ink" as const, publisher: "77120", publisherNote: null, icon: 0.25, outcome: { level: "low" as const, score: 35 } },
];

export function AppPreview() {
  return (
    <Frame title="App Store Monitoring · listings for “northvale pay”">
      <table className="w-full table-fixed text-left text-[12.5px]">
        <colgroup>
          <col />
          <col className="hidden w-[112px] sm:table-column" />
          <col className="hidden w-[104px] sm:table-column" />
          <col className="w-[112px]" />
        </colgroup>
        <thead className="border-b border-ink-150 bg-ink-50/70 text-[11px] text-ink-500">
          <tr>
            <th scope="col" className="py-2 pr-2 pl-4 font-medium">Listing</th>
            <th scope="col" className="hidden px-2.5 py-2 font-medium sm:table-cell">Publisher ID</th>
            <th scope="col" className="hidden px-2.5 py-2 font-medium sm:table-cell">Icon match</th>
            <th scope="col" className="py-2 pr-4 pl-2.5 font-medium">Outcome</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-150">
          {APP_ROWS.map((r) => (
            <tr key={r.id} className={r.outcome !== "official" && r.outcome.level === "critical" ? "bg-crit-bg/40" : undefined}>
              <td className="py-3 pr-2 pl-4">
                <div className="flex items-center gap-2.5">
                  <Initial letter={r.letter} square tone={r.tone} />
                  <div className="min-w-0">
                    <div className="font-medium text-ink-900">{r.name}</div>
                    <div className="truncate font-mono text-[11px] text-ink-500">{r.id}</div>
                    {/* On phones the publisher column collapses into the listing cell. */}
                    <div className="mt-0.5 font-mono text-[11px] text-ink-600 sm:hidden">
                      publisher {r.publisher}
                      {r.publisherNote && <span className="font-sans text-crit"> · not official</span>}
                    </div>
                  </div>
                </div>
              </td>
              <td className="hidden px-2.5 py-3 sm:table-cell">
                <div className="font-mono text-[11.5px] text-ink-700">{r.publisher}</div>
                {r.publisherNote && <div className="text-[11px] leading-snug text-crit">{r.publisherNote}</div>}
              </td>
              <td className="hidden px-2.5 py-3 sm:table-cell">
                {r.icon === null ? <span className="text-ink-400">—</span> : <ScoreMeter value={r.icon} className="[&>span:first-child]:w-10" />}
              </td>
              <td className="py-3 pr-4 pl-2.5">
                {r.outcome === "official" ? (
                  <span className="inline-flex items-center gap-1 text-[12px] leading-tight font-medium text-forest-600">
                    <ShieldCheck className="size-3.5 shrink-0" aria-hidden /> Official · excluded
                  </span>
                ) : (
                  <RiskBadge level={r.outcome.level} score={r.outcome.score} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-ink-150 px-4 py-2.5 text-[11.5px] text-ink-500">
        A different publisher alone stays <span className="font-medium text-ink-700">Low</span>. Copied icon, credential wording and a look-alike support domain raise it.
      </p>
    </Frame>
  );
}

// ---------------------------------------------------------------- 4. Official-asset protection

export function AssetsPreview() {
  return (
    <Frame title="Brand profile · Northvale Pay" dark>
      <div className="grid gap-px bg-ink-700 sm:grid-cols-2">
        <div className="bg-ink-850 p-4">
          <div className="text-[11px] tracking-wide text-ink-500 uppercase">Names & aliases</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {["Northvale Pay", "Northvale", "NV Pay"].map((n) => (
              <span key={n} className="rounded-[4px] border border-ink-700 bg-ink-800 px-2 py-0.5 text-[12px] text-ink-100">{n}</span>
            ))}
          </div>
          <div className="mt-4 text-[11px] tracking-wide text-ink-500 uppercase">Official domains</div>
          <div className="mt-2 space-y-1 font-mono text-[12px] text-ink-200">
            <div>northvalepay.example</div>
            <div>northvale.example</div>
          </div>
        </div>
        <div className="bg-ink-850 p-4">
          <div className="text-[11px] tracking-wide text-ink-500 uppercase">Official assets</div>
          <ul className="mt-2 space-y-2 text-[12px]">
            {[
              { p: "bluesky", id: "@northvalepay.example" },
              { p: "mastodon", id: "@northvale@mastodon.example" },
              { p: "apple", id: "com.northvale.pay · id1550000001" },
              { p: "google_play", id: "com.northvale.pay" },
            ].map((a) => (
              <li key={a.id} className="flex items-center gap-2 text-ink-200">
                <PlatformGlyph platform={a.p} className="text-teal-400" />
                <span className="truncate font-mono text-[11.5px]">{a.id}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="border-t border-ink-700 px-4 py-3">
        <div className="mb-2 text-[11px] tracking-wide text-ink-500 uppercase">Exclusion audit · scan #4</div>
        <ul className="space-y-1.5 font-mono text-[11.5px]">
          {[
            ["official_platform_handle", "bluesky:@northvalepay.example"],
            ["official_app_id", "apple:com.northvale.pay"],
            ["official_app_id", "google_play:com.northvale.pay"],
          ].map(([rule, v]) => (
            <li key={v} className="flex flex-wrap items-center gap-x-2 text-ink-300">
              <ShieldCheck className="size-3.5 text-teal-400" aria-hidden />
              <span className="text-teal-400">{rule}</span>
              <span className="text-ink-500">{v}</span>
            </li>
          ))}
          <li className="flex flex-wrap items-center gap-x-2 text-ink-300">
            <CircleSlash className="size-3.5 text-[#e0a37f]" aria-hidden />
            <span className="text-[#e0a37f]">not excluded</span>
            <span className="text-ink-500">developer “Northvale Pay Inc Support” — display names are never trusted</span>
          </li>
        </ul>
      </div>
    </Frame>
  );
}

// ---------------------------------------------------------------- 5. Investigations

export function InvestigationPreview() {
  const groups: [string, number | null, boolean][] = [
    ["Name / handle", 0.89, false],
    ["Logo", 0.97, true],
    ["Links", 0.98, true],
    ["Scam indicators", 0.89, true],
    ["Description", 0.0, false],
  ];
  return (
    <Frame title="Investigation · finding #12">
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[14px] font-semibold text-ink-950">Northvale Pay Support</span>
          <SourceTypeBadge type="simulated" />
          <ChangeBadge state="changed" />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <RiskBadge level="critical" score={82} />
          <span className="text-[12.5px] font-medium text-ink-900">Potential impersonation with scam indicators — review required</span>
        </div>
        <p className="mt-3 rounded-md border border-ink-150 bg-ink-50 px-3 py-2 text-[12.5px] leading-relaxed text-ink-700">
          Identity similarity 0.89 (brand name plus impersonation terms: support). Corroborated by logo similarity, suspicious links, scam indicators.
        </p>
        <ul className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {groups.map(([g, v, c]) => (
            <li key={g} className="flex items-center justify-between gap-3 text-[12px]">
              <span className={clsx(c ? "font-medium text-ink-900" : "text-ink-600")}>
                {g}
                {c && <span className="text-forest-600"> ✓</span>}
              </span>
              <ScoreMeter value={v ?? 0} evaluated={v !== null} />
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11.5px] text-ink-500">
          <span className="font-medium text-ink-700">Changed since last scan:</span> bio now asks visitors to verify their account at northvalepay-verify.top.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-ink-150 pt-3.5" aria-hidden>
          <span className="inline-flex h-7 items-center rounded-md bg-forest-700 px-2.5 text-[12px] font-medium text-white">Confirm impersonation</span>
          <span className="inline-flex h-7 items-center rounded-md border border-ink-200 bg-paper px-2.5 text-[12px] font-medium text-ink-800">Mark legitimate</span>
          <span className="ml-auto text-[11px] text-ink-400">Decisions are logged with analyst and time</span>
        </div>
      </div>
    </Frame>
  );
}

// ---------------------------------------------------------------- 6. Source coverage

export const SOURCES = [
  { name: "Bluesky", platform: "bluesky", access: "Public AppView actor search", kind: "Official public API", note: "Names, handles, bios, avatars" },
  { name: "Mastodon", platform: "mastodon", access: "Instance account search", kind: "Official public API", note: "Only what your configured instances know about" },
  { name: "Apple App Store", platform: "apple", access: "iTunes Search API", kind: "Official public API", note: "Rate-limited by Apple (~20 requests/min)" },
  { name: "Google Play", platform: "google_play", access: "google-play-scraper", kind: "Unofficial", note: "Parses public pages — may slow down or break" },
];

export const NOT_INTEGRATED = ["X (Twitter)", "Instagram", "Facebook", "TikTok"];

export function NotIntegratedIcon() {
  return <Ban className="size-3.5 text-ink-400" aria-hidden />;
}

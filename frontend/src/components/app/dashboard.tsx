"use client";

import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, ChevronLeft, ChevronRight, ClipboardCheck, Radar, SearchX, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { dateTime, duration, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Dashboard, Finding, Level4, Paged, Scan } from "@/lib/types";
import { Button, Card, CardHeader, EmptyState, ErrorState, ProgressBar, Skeleton, cx } from "../ui";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, SOURCE_HEALTH_LABEL, sourceDot, SourceTypeBadge, StatusBadge, StatusDot } from "./bits";
import { SEVERITY_RAMP } from "./charts";
import { useScans } from "./providers";

const LEVELS: Level4[] = ["critical", "high", "medium", "low"];
const LEVEL_LABEL: Record<Level4, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

export const RANGES = [
  { value: "1", label: "24h" },
  { value: "7", label: "7d" },
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "all", label: "All" },
] as const;
export type RangeValue = (typeof RANGES)[number]["value"];

export function rangeLabel(r: RangeValue) {
  return r === "all" ? "all time" : r === "1" ? "the last 24 hours" : `the last ${r} days`;
}

/** "“a”: x timed out; “b”: x timed out; skipped …" → "x timed out (2 queries) · skipped …" */
export function summarizeSourceError(err: string | null | undefined): string {
  if (!err) return "";
  const counts = new Map<string, number>();
  for (const part of err.split(/;\s*/).filter(Boolean)) {
    const msg = part.replace(/^“[^”]*”:\s*/, "").trim();
    counts.set(msg, (counts.get(msg) ?? 0) + 1);
  }
  return [...counts].map(([m, n]) => (n > 1 ? `${m} (${n} queries)` : m)).join(" · ");
}

// ---------------------------------------------------------------- Scan status (live progress → final result)

function SourceRows({ scan }: { scan: Scan }) {
  return (
    <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
      {scan.sources.map((s) => (
        <li key={s.source} className="flex min-w-0 items-center gap-2 text-[12.5px]">
          <StatusDot status={s.status} />
          <span className="w-24 shrink-0 text-ink-800">{sourceLabel(s.source)}</span>
          <span className="tabular truncate text-[11.5px] text-ink-500" title={s.error ?? undefined}>
            {s.status === "pending" ? "waiting" : `${s.queries_done}/${s.queries_total} queries · ${s.candidates} found`}
            {s.queries_failed > 0 && <span className="text-crit"> · {s.queries_failed} failed</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Live progress for a running scan of this brand, then the final outcome of the last scan this session saw finish. */
export function ScanStatusPanel({ brandId }: { brandId: number }) {
  const { active, lastFinished } = useScans();
  const running = active.find((s) => s.brand_id === brandId);
  const [dismissedId, setDismissedId] = useState<number | null>(null);

  if (running) {
    return (
      <Card className="border-teal-200 p-4 animate-fade-in" role="status" aria-live="polite">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-[13px] font-medium text-ink-900">
            <StatusDot status="running" /> Scan #{running.id} in progress
            <span className="font-normal text-ink-500">· {running.stage}</span>
          </div>
          <span className="tabular text-[12.5px] text-ink-600">{Math.round(running.progress * 100)}%</span>
        </div>
        <ProgressBar value={running.progress} className="mt-3" />
        <div className="mt-3">
          <SourceRows scan={running} />
        </div>
        <p className="mt-2.5 text-[11.5px] text-ink-500">Progress counts completed source queries, then logo comparison and scoring. Each source runs independently.</p>
      </Card>
    );
  }
  if (!lastFinished || lastFinished.brand_id !== brandId || dismissedId === lastFinished.id) return null;
  const s = lastFinished;
  const failed = s.sources.filter((x) => x.status === "failed");
  const partial = s.sources.filter((x) => x.status === "partial");
  const tone = s.status === "failed" ? "border-[#efcdc4] bg-crit-bg/50" : s.status === "partial" ? "border-[#ebdcae] bg-med-bg/50" : "border-forest-100 bg-forest-50/60";
  const Icon = s.status === "completed" ? CheckCircle2 : AlertTriangle;
  return (
    <div role="status" className={cx("rounded-lg border px-4 py-3 animate-fade-in", tone)}>
      <div className="flex items-start gap-3">
        <Icon className={cx("mt-0.5 size-4 shrink-0", s.status === "completed" ? "text-forest-600" : s.status === "partial" ? "text-med" : "text-crit")} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-ink-900">
            Scan #{s.id} {s.status === "completed" ? "completed" : s.status === "partial" ? "finished with source errors" : "failed"}
            <span className="font-normal text-ink-500"> · {relTime(s.finished_at)}</span>
          </div>
          <div className="tabular mt-0.5 text-[12.5px] text-ink-700">
            {s.candidates_unique} candidates · {s.excluded_official} official excluded · <strong className="font-medium">{s.findings_new}</strong> new ·{" "}
            {s.findings_changed} changed · {s.findings_resolved} no longer seen
          </div>
          {(failed.length > 0 || partial.length > 0) && (
            <ul className="mt-1.5 space-y-0.5 text-[12px]">
              {[...failed, ...partial].map((x) => (
                <li key={x.source} className="text-ink-700">
                  <span className="font-medium">{sourceLabel(x.source)}</span> {x.status === "failed" ? "failed" : "partial"}
                  {x.error && <span className="text-ink-500"> — {summarizeSourceError(x.error)}</span>}
                </li>
              ))}
              <li className="text-[11.5px] text-ink-500">Results from failed sources are missing, not replaced. Their findings are not marked as resolved.</li>
            </ul>
          )}
          {s.status === "failed" && s.error && <div className="mt-1 text-[12px] text-crit">{s.error}</div>}
        </div>
        <Link href={`/app/scans/${s.id}`} className="shrink-0 text-[12px] font-medium text-teal-700 hover:underline">Details</Link>
        <button aria-label="Dismiss scan result" onClick={() => setDismissedId(s.id)} className="rounded p-0.5 text-ink-400 hover:bg-white/60 hover:text-ink-700">
          <X className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Metrics strip

function Metric({ label, value, sub, href, tone, scope }: { label: string; value: number; sub: React.ReactNode; href: string; tone?: "crit" | "warn"; scope: "period" | "now" }) {
  return (
    <Link href={href} className="group block min-w-0 px-4 py-3.5 transition-colors hover:bg-white focus-visible:bg-white">
      <div className="flex items-center justify-between gap-2 text-[11.5px] text-ink-500">
        <span className="leading-tight">{label}</span>
        <span className="hidden shrink-0 rounded-[3px] border border-ink-150 px-1 text-[10px] tracking-wide text-ink-400 uppercase sm:inline" title={scope === "period" ? "Within the selected date range" : "Current state, not date-filtered"}>
          {scope === "period" ? "period" : "now"}
        </span>
      </div>
      <div className={cx("tabular mt-1.5 text-[26px] leading-none font-semibold tracking-[-0.03em]", tone === "crit" && value > 0 ? "text-crit" : tone === "warn" && value > 0 ? "text-med" : "text-ink-950")}>
        {value.toLocaleString()}
      </div>
      <div className="mt-1.5 line-clamp-2 text-[11.5px] leading-snug text-ink-500">{sub}</div>
    </Link>
  );
}

export function MetricsStrip({ d, brandId, range }: { d: Dashboard; brandId: number; range: RangeValue }) {
  const m = d.metrics;
  return (
    <Card className="grid grid-cols-2 divide-ink-150 overflow-hidden sm:grid-cols-3 lg:grid-cols-5 lg:divide-x [&>*]:border-ink-150 max-lg:[&>*]:border-b">
      <Metric scope="period" label="Candidates scanned" value={m.candidates_scanned} href="/app/scans"
        sub={m.scans_in_period ? `${m.scans_in_period} scan${m.scans_in_period === 1 ? "" : "s"} in ${rangeLabel(range)}` : `No scans in ${rangeLabel(range)}`} />
      <Metric scope="now" label="Requires review" value={m.review_required} href="/app/review"
        sub={m.review_required ? `${d.review.new_or_changed} new or changed` : "Queue is clear"} />
      <Metric scope="now" label="High-risk findings" value={m.high_risk_open} tone="crit" href="/app/investigations?level=critical&level=high&status=open"
        sub={`${m.critical_open} critical · ${m.high_risk_open - m.critical_open} high`} />
      <Metric scope="now" label="Official assets excluded" value={m.official_excluded} href={`/app/brands/${brandId}#exclusions`} sub="Matched by exact identifier" />
      <Metric scope="now" label="Sources unavailable" value={m.sources_unavailable} tone="warn" href="/app/sources"
        sub={m.sources_unavailable ? d.unavailable_sources.join(", ") : m.sources_degraded ? `${m.sources_degraded} returning partial results` : `All ${m.sources_enabled} enabled sources responding`} />
    </Card>
  );
}

// ---------------------------------------------------------------- Recent detections (filters, sorting, pagination)

const PAGE = 8;
type SortKey = "risk" | "last_seen" | "name";

export function DetectionsTable({ brandId, range }: { brandId: number; range: RangeValue }) {
  const router = useRouter();
  const { version } = useScans();
  const [levels, setLevels] = useState<Level4[]>(["critical", "high", "medium"]);
  const [sort, setSort] = useState<SortKey>("risk");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [brandId, range, levels, sort, order]);

  const { data, error, loading, reload } = useApi<Paged<Finding>>("/findings", {
    brand_id: brandId,
    level: levels.length ? levels : LEVELS,
    since_days: range === "all" ? undefined : range,
    sort,
    order,
    limit: PAGE,
    offset: page * PAGE,
  });
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);

  const toggleSort = (k: SortKey) => {
    if (sort === k) setOrder((o) => (o === "desc" ? "asc" : "desc"));
    else {
      setSort(k);
      setOrder(k === "name" ? "asc" : "desc");
    }
  };
  const Th = ({ k, children, className }: { k: SortKey; children: React.ReactNode; className?: string }) => (
    <th scope="col" className={cx("px-3 py-2 font-medium", className)} aria-sort={sort === k ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => toggleSort(k)} className={cx("inline-flex items-center gap-1 hover:text-ink-900", sort === k && "text-ink-900")}>
        {children}
        {sort === k && (order === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
      </button>
    </th>
  );
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <Card className="min-w-0">
      <CardHeader
        title="Recent detections"
        description={`Seen in ${rangeLabel(range)} · click a row to investigate`}
        actions={
          <div role="group" aria-label="Severity filter" className="flex flex-wrap gap-1">
            {LEVELS.map((l) => {
              const on = levels.includes(l);
              return (
                <button
                  key={l}
                  aria-pressed={on}
                  onClick={() => setLevels((ls) => (on ? ls.filter((x) => x !== l) : [...ls, l]))}
                  className={cx("inline-flex h-6 items-center gap-1.5 rounded-[5px] border px-2 text-[11.5px] font-medium transition-colors", on ? "border-ink-800 bg-ink-800 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300")}
                >
                  <span className="size-1.5 rounded-full" style={{ background: SEVERITY_RAMP[l] }} aria-hidden />
                  {LEVEL_LABEL[l]}
                </button>
              );
            })}
          </div>
        }
      />
      {error && <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-[12.5px]">
          <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
            <tr>
              <Th k="name" className="pl-4">Candidate</Th>
              <th scope="col" className="px-3 py-2 font-medium">Source</th>
              <Th k="risk">Risk</Th>
              <th scope="col" className="px-3 py-2 font-medium">Change</th>
              <th scope="col" className="px-3 py-2 font-medium">Status</th>
              <Th k="last_seen" className="pr-4">Last seen</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-150">
            {loading && !data
              ? Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}><td colSpan={6} className="px-4 py-2.5"><Skeleton className="h-6" /></td></tr>
                ))
              : data?.items.map((f) => (
                  <tr
                    key={f.id}
                    tabIndex={0}
                    onClick={() => router.push(`/app/investigations/${f.id}`)}
                    onKeyDown={(e) => e.key === "Enter" && router.push(`/app/investigations/${f.id}`)}
                    className="cursor-pointer transition-colors hover:bg-white focus-visible:bg-white"
                  >
                    <td className="py-2 pr-3 pl-4">
                      <div className="flex items-center gap-2.5">
                        <Avatar url={f.candidate.avatar_url} name={f.candidate.name} size={26} square={f.candidate.kind === "app"} />
                        <div className="min-w-0">
                          <Link href={`/app/investigations/${f.id}`} onClick={(e) => e.stopPropagation()} className="block max-w-[220px] truncate font-medium text-ink-900 hover:underline">
                            {f.candidate.name}
                          </Link>
                          <div className="max-w-[220px] truncate text-[11px] text-ink-500">
                            {f.candidate.kind === "app" ? f.candidate.publisher_name ?? f.candidate.external_id : f.candidate.handle ? `@${f.candidate.handle}` : f.candidate.external_id}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5 text-ink-700"><PlatformGlyph platform={f.candidate.platform} className="text-ink-500" />{sourceLabel(f.candidate.platform)}</span>
                      {f.candidate.source_type !== "live" && <div className="mt-0.5"><SourceTypeBadge type={f.candidate.source_type} /></div>}
                    </td>
                    <td className="px-3 py-2"><RiskBadge level={f.risk_level} score={f.risk_score} /></td>
                    <td className="px-3 py-2"><ChangeBadge state={f.change_state} /></td>
                    <td className="px-3 py-2"><StatusBadge status={f.status} level={f.risk_level} /></td>
                    <td className="tabular py-2 pr-4 pl-3 text-ink-500" title={dateTime(f.candidate.last_observed_at)}>{relTime(f.candidate.last_observed_at)}</td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {data && data.items.length === 0 && (
        <EmptyState
          icon={<SearchX className="size-5" />}
          title={levels.length < 4 ? "No detections at these severities" : "No detections in this period"}
          description={levels.length < 4 ? "Include lower severities or widen the date range." : "Widen the date range or run a scan."}
        />
      )}
      {data && total > 0 && (
        <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2 text-[12px] text-ink-500">
          <span className="tabular">
            {page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total}
          </span>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="size-3.5" /></Button>
            <span className="tabular px-1">{page + 1} / {pages}</span>
            <Button size="sm" variant="ghost" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="size-3.5" /></Button>
            <Link href="/app/investigations" className="ml-2 font-medium text-teal-700 hover:underline">All investigations</Link>
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- Severity × platform

export function SeverityPlatformMatrix({ d, range }: { d: Dashboard; range: RangeValue }) {
  const rows = d.severity_by_platform;
  const max = Math.max(1, ...rows.flatMap((r) => LEVELS.map((l) => r[l])));
  return (
    <Card className="min-w-0">
      <CardHeader title="Open findings by severity and platform" description={`Observed in ${rangeLabel(range)} · select a cell to investigate`} />
      {rows.length === 0 ? (
        <EmptyState icon={<ShieldCheck className="size-5" />} title="No open findings in this period" description="Nothing observed in the selected range is awaiting a decision." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-[12.5px]">
            <caption className="sr-only">Open findings by platform and severity</caption>
            <thead className="text-[11.5px] text-ink-500">
              <tr className="border-b border-ink-150">
                <th scope="col" className="py-2 pr-3 pl-4 text-left font-medium">Platform</th>
                {LEVELS.map((l) => (
                  <th key={l} scope="col" className="px-1.5 py-2 text-center font-medium">{LEVEL_LABEL[l]}</th>
                ))}
                <th scope="col" className="py-2 pr-4 pl-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {rows.map((r) => (
                <tr key={r.platform}>
                  <th scope="row" className="py-1.5 pr-3 pl-4 text-left font-normal text-ink-800">
                    <span className="inline-flex items-center gap-1.5"><PlatformGlyph platform={r.platform} className="text-ink-500" />{sourceLabel(r.platform)}</span>
                  </th>
                  {LEVELS.map((l) => {
                    const n = r[l];
                    const strong = n / max > 0.55;
                    return (
                      <td key={l} className="px-1 py-1">
                        {n ? (
                          <Link
                            href={`/app/investigations?level=${l}&source=${r.platform}&status=open`}
                            className={cx("tabular block rounded-[4px] py-1.5 text-center font-medium transition-[filter] hover:brightness-95", strong ? "text-white" : "text-ink-900")}
                            style={{ background: `color-mix(in srgb, ${SEVERITY_RAMP[l]} ${Math.round(25 + (n / max) * 75)}%, white)` }}
                            aria-label={`${n} ${LEVEL_LABEL[l].toLowerCase()} on ${sourceLabel(r.platform)}`}
                          >
                            {n}
                          </Link>
                        ) : (
                          <span className="block py-1.5 text-center text-ink-300" aria-label="none">·</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="tabular py-1.5 pr-4 pl-2 text-right font-medium text-ink-900">{r.total}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t border-ink-150 text-[11.5px] text-ink-600">
              <tr>
                <th scope="row" className="py-2 pr-3 pl-4 text-left font-medium">All platforms</th>
                {LEVELS.map((l) => (
                  <td key={l} className="tabular px-1.5 py-2 text-center">{d.severity_period[l]}</td>
                ))}
                <td className="tabular py-2 pr-4 pl-2 text-right font-medium text-ink-900">{rows.reduce((s, r) => s + r.total, 0)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- Review queue summary

export function ReviewSummary({ d }: { d: Dashboard }) {
  const r = d.review;
  const total = r.open_by_level.critical + r.open_by_level.high + r.open_by_level.medium;
  return (
    <Card>
      <CardHeader
        title="Review queue"
        description={total ? `Oldest waiting ${relTime(r.oldest_open_at)}` : "Medium severity and above"}
        actions={<Link href="/app/review" className="inline-flex items-center gap-1 text-[12px] font-medium text-teal-700 hover:underline"><ClipboardCheck className="size-3.5" /> Open queue</Link>}
      />
      {total === 0 ? (
        <EmptyState icon={<CheckCircle2 className="size-5" />} title="Nothing waiting for review" description="Low-confidence name matches are still listed in Investigations." className="py-8" />
      ) : (
        <>
          <dl className="grid grid-cols-3 divide-x divide-ink-150 border-b border-ink-150">
            {(["critical", "high", "medium"] as const).map((l) => (
              <Link key={l} href={`/app/investigations?level=${l}&status=open`} className="px-4 py-2.5 hover:bg-white">
                <dt className="flex items-center gap-1.5 text-[11.5px] text-ink-500"><span className="size-1.5 rounded-full" style={{ background: SEVERITY_RAMP[l] }} />{LEVEL_LABEL[l]}</dt>
                <dd className="tabular mt-0.5 text-[18px] font-semibold text-ink-950">{r.open_by_level[l]}</dd>
              </Link>
            ))}
          </dl>
          <ul className="divide-y divide-ink-150">
            {r.top.map((f) => (
              <li key={f.id}>
                <Link href={`/app/investigations/${f.id}`} className="flex items-center gap-2.5 px-4 py-2 hover:bg-white">
                  <PlatformGlyph platform={f.candidate.platform} className="text-ink-400" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-900">{f.candidate.name}</span>
                  <RiskBadge level={f.risk_level} score={f.risk_score} />
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- Source health

export function SourceHealthCard({ d }: { d: Dashboard }) {
  return (
    <Card>
      <CardHeader title="Source health" description="From real scans and connectivity tests — never assumed" actions={<Link href="/app/sources" className="text-[12px] font-medium text-teal-700 hover:underline">Manage</Link>} />
      <ul className="divide-y divide-ink-150">
        {d.source_health.map((s) => (
          <li key={s.name} className="px-4 py-2.5">
            <div className="flex items-center gap-2">
              <StatusDot status={sourceDot(s)} />
              <span className="flex-1 text-[12.5px] font-medium text-ink-900">
                {s.label}
                {s.reliability === "unofficial" && <span className="ml-1.5 text-[11px] font-normal text-ink-400">unofficial</span>}
              </span>
              <span className={cx("text-[11.5px]", s.unavailable ? "font-medium text-crit" : s.health === "degraded" ? "text-med" : "text-ink-500")}>
                {!s.enabled ? "Disabled" : s.state === "unavailable" ? `Unavailable · ${SOURCE_HEALTH_LABEL[s.health] ?? s.health}` : SOURCE_HEALTH_LABEL[s.health] ?? s.health}
              </span>
            </div>
            <div className="mt-0.5 pl-4 text-[11.5px] text-ink-500">
              {s.last_success_at ? (
                s.last_success_scan_id ? (
                  <>Last successful request <Link href={`/app/scans/${s.last_success_scan_id}`} className="text-ink-700 hover:underline">{relTime(s.last_success_at)}</Link></>
                ) : (
                  <>Last successful request {relTime(s.last_success_at)} (connectivity test)</>
                )
              ) : s.health === "simulated" ? (
                "Synthetic dataset — no network requests"
              ) : (
                "No successful request yet"
              )}
              {s.checked_at && <> · checked {relTime(s.checked_at)}</>}
            </div>
            {(s.unavailable || s.health === "degraded") && s.detail && <div className="mt-0.5 line-clamp-2 pl-4 text-[11.5px] text-ink-500" title={s.detail}>{summarizeSourceError(s.detail)}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- Recent scans

export function RecentScans({ d, range }: { d: Dashboard; range: RangeValue }) {
  return (
    <Card>
      <CardHeader title="Recent scans" description={`In ${rangeLabel(range)}`} actions={<Link href="/app/scans" className="text-[12px] font-medium text-teal-700 hover:underline">History</Link>} />
      {d.recent_scans.length === 0 ? (
        <EmptyState icon={<Radar className="size-5" />} title="No scans in this period" className="py-8" />
      ) : (
        <ul className="divide-y divide-ink-150">
          {d.recent_scans.map((s) => {
            const failed = s.sources.filter((x) => x.status === "failed").length;
            const partial = s.sources.filter((x) => x.status === "partial").length;
            return (
              <li key={s.id}>
                <Link href={`/app/scans/${s.id}`} className="grid grid-cols-[auto_1fr_auto] items-center gap-x-2.5 px-4 py-2 hover:bg-white">
                  <StatusDot status={s.status} />
                  <div className="min-w-0">
                    <div className="truncate text-[12.5px] text-ink-900">
                      #{s.id} <span className="text-ink-500 capitalize">· {s.trigger}</span>
                      {s.mode === "demo" && <span className="text-med"> · synthetic</span>}
                      {s.mode === "import" && <span className="text-ink-500"> · import</span>}
                    </div>
                    <div className="tabular truncate text-[11.5px] text-ink-500">
                      {s.status === "running" || s.status === "queued" ? `${Math.round(s.progress * 100)}% · ${s.stage}` : `${s.candidates_unique} candidates · ${s.findings_new} new · ${s.findings_changed} changed`}
                      {failed > 0 && <span className="text-crit"> · {failed} source{failed > 1 ? "s" : ""} failed</span>}
                      {partial > 0 && <span className="text-med"> · {partial} partial</span>}
                    </div>
                  </div>
                  <span className="text-right text-[11px] text-ink-400">
                    {relTime(s.created_at)}
                    {s.started_at && s.finished_at && <span className="block">{duration(new Date(s.finished_at).getTime() - new Date(s.started_at).getTime())}</span>}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

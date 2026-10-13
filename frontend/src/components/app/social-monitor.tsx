"use client";

import { ArrowUpRight, Check, ChevronLeft, ChevronRight, ExternalLink, Info, Radar, RotateCcw, Search, SearchX, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { dateTime, DETECTION_TYPE_LABELS, duration, OUTCOME_LABELS, relTime, safeHref, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Finding, Paged, Scan, ScanSource } from "@/lib/types";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Notice, ProgressBar, Select, Skeleton, cx } from "../ui";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, SOURCE_STATUS_LABEL, SourceTypeBadge, StatusBadge, StatusDot } from "./bits";
import { summarizeSourceError } from "./dashboard";
import { useBrands, useScans } from "./providers";

const SOCIAL = ["bluesky", "mastodon", "youtube"] as const;
const LEVELS = ["critical", "high", "medium", "low"] as const;
const ACCOUNT_TYPES = ["fake_brand_page", "fake_profile", "scam_account", "lookalike_account"];
const SIGNALS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "handle", label: "Handle" },
  { key: "logo", label: "Logo" },
  { key: "description", label: "Bio text" },
  { key: "urls", label: "Links" },
  { key: "scam", label: "Scam cues" },
];
const PAGE = 10;

export function endpointLabel(endpoint: string | undefined, source: string) {
  if (!endpoint) return sourceLabel(source);
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint; // e.g. "CSV upload"
  }
}

// ---------------------------------------------------------------- scan workflow & summary

const STEPS = [
  "Select brand",
  "Load official assets",
  "Generate look-alike queries",
  "Query sources",
  "Normalize & de-duplicate",
  "Exclude official assets",
  "Run detection",
  "Persist findings",
  "Summary",
];

function stepFor(scan: Scan): number {
  if (scan.status !== "running" && scan.status !== "queued") return 9;
  const s = scan.stage.toLowerCase();
  if (s.includes("queued")) return 1;
  if (s.includes("search terms")) return 3;
  if (s.includes("collecting")) return 4;
  if (s.includes("logo")) return 6;
  if (s.includes("scoring")) return 7;
  return 4;
}

export function WorkflowProgress({ scan }: { scan: Scan }) {
  const current = stepFor(scan);
  return (
    <Card className="p-4" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <span className="inline-flex items-center gap-2 font-medium text-ink-900"><StatusDot status="running" /> Scan #{scan.id} · {scan.stage}</span>
        <span className="tabular text-ink-600">{Math.round(scan.progress * 100)}%</span>
      </div>
      <ProgressBar value={scan.progress} className="mt-2.5" />
      <ol className="mt-3 grid gap-x-4 gap-y-1 text-[11.5px] sm:grid-cols-3 lg:grid-cols-5">
        {STEPS.map((label, i) => {
          const n = i + 1;
          return (
            <li key={label} className={cx("flex items-center gap-1.5", n < current ? "text-forest-700" : n === current ? "font-medium text-ink-900" : "text-ink-400")}>
              <span className={cx("grid size-4 place-items-center rounded-full border text-[9.5px]", n < current ? "border-forest-600 bg-forest-600 text-white" : n === current ? "border-teal-500 text-teal-700" : "border-ink-200")}>
                {n < current ? <Check className="size-2.5" strokeWidth={3} /> : n}
              </span>
              {label}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

export function sourceStatusLabel(s: ScanSource) {
  if (s.status === "failed" && s.failure_kind) return OUTCOME_LABELS[s.failure_kind] ?? "Failed";
  if (s.status === "partial" && s.failure_kind) return `Partial — ${(OUTCOME_LABELS[s.failure_kind] ?? s.failure_kind).toLowerCase()}`;
  return SOURCE_STATUS_LABEL[s.status] ?? s.status;
}

export function ScanSummary({ scan, include = SOCIAL, title = "Last social scan" }: { scan: Scan; include?: readonly string[]; title?: string }) {
  const sources = scan.sources.filter((s) => include.includes(s.source) || s.source === "demo");
  return (
    <Card>
      <CardHeader
        title={`${title} · #${scan.id}`}
        description={`${scan.trigger} · finished ${relTime(scan.finished_at)} · ${scan.candidates_unique} unique candidates · ${scan.excluded_official} official excluded · ${scan.findings_new} new · ${scan.findings_changed} changed`}
        actions={<Link href={`/app/scans/${scan.id}`} className="text-[12px] font-medium text-teal-700 hover:underline">Scan details</Link>}
      />
      <ul className="grid divide-y divide-ink-150 md:grid-cols-2 md:divide-x md:divide-y-0">
        {sources.map((s) => {
          const outcomes = Object.entries(s.query_outcomes ?? {}).filter(([, n]) => n > 0);
          const rl = s.rate_limit ? Object.entries(s.rate_limit as Record<string, { remaining?: number | null; limit?: number | null }>) : [];
          return (
            <li key={s.source} className="px-4 py-3">
              <div className="flex items-center gap-2">
                <PlatformGlyph platform={s.source === "demo" ? include[0] : s.source} className="text-ink-500" />
                <span className="text-[13px] font-medium text-ink-900">{sourceLabel(s.source)}</span>
                <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-ink-700"><StatusDot status={s.status} />{sourceStatusLabel(s)}</span>
              </div>
              <div className="tabular mt-1 text-[11.5px] text-ink-500">
                {s.queries_done}/{s.queries_total} queries · {s.candidates} candidates · {duration(s.duration_ms)}
              </div>
              {outcomes.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {outcomes.map(([k, n]) => (
                    <Badge key={k} tone={k === "ok" ? "forest" : k === "empty" ? "neutral" : k === "rate_limited" || k === "timeout" ? "med" : "crit"}>
                      {OUTCOME_LABELS[k] ?? k} · {n}
                    </Badge>
                  ))}
                </div>
              )}
              {rl.map(([inst, v]) => v?.limit != null && (
                <div key={inst} className="mt-1 text-[11px] text-ink-500">Rate limit{inst !== "default" ? ` (${inst})` : ""}: {v.remaining ?? "?"}/{v.limit} remaining</div>
              ))}
              {s.error && <p className="mt-1 line-clamp-2 text-[11.5px] text-ink-500" title={s.error}>{summarizeSourceError(s.error)}</p>}
            </li>
          );
        })}
      </ul>
      {scan.search_terms.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-ink-150 px-4 py-2.5 text-[11.5px] text-ink-500">
          Look-alike queries:
          {scan.search_terms.map((t) => <code key={t} className="rounded-[3px] border border-ink-150 bg-white px-1.5 py-px font-mono text-[11px] text-ink-700">{t}</code>)}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- candidate card

export function SignalMeter({ label, s }: { label: string; s?: { score: number; evaluated: boolean; detail: string } }) {
  const v = s?.score ?? 0;
  const evaluated = !!s?.evaluated;
  const color = v >= 0.75 ? "bg-crit" : v >= 0.5 ? "bg-high" : v >= 0.3 ? "bg-med" : "bg-ink-300";
  return (
    <div className="min-w-0" title={s?.detail || (evaluated ? "" : "Not evaluated")}>
      <div className="flex items-baseline justify-between gap-1 text-[10.5px]">
        <span className="truncate text-ink-500">{label}</span>
        <span className={cx("tabular", evaluated ? "text-ink-800" : "text-ink-400")}>{evaluated ? `${Math.round(v * 100)}` : "n/a"}</span>
      </div>
      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-ink-100">
        {evaluated && <div className={cx("h-full rounded-full", color)} style={{ width: `${Math.max(3, v * 100)}%` }} />}
      </div>
    </div>
  );
}

function CandidateCard({ f, onChange }: { f: Finding; onChange: (f: Finding) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const c = f.candidate;
  const profile = c.source_type === "simulated" ? undefined : safeHref(c.url);
  const prov = c.provenance as { endpoint?: string; query?: string; queries?: string[]; adapter?: string };
  const queries = (prov.queries?.length ? prov.queries : prov.query ? [prov.query] : []).slice(0, 4);

  const decide = async (action: "confirm" | "mark_safe" | "reopen") => {
    setBusy(action);
    try {
      const updated = await api<Finding>(`/findings/${f.id}/decision`, { method: "POST", body: { action, note: "" } });
      onChange({ ...f, status: updated.status });
      toast({ tone: "success", title: { confirm: "Confirmed as impersonation", mark_safe: "Marked legitimate", reopen: "Reopened" }[action] });
    } catch (e) {
      toast({ tone: "error", title: "Could not save decision", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="px-4 py-4" aria-labelledby={`cand-${f.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <Avatar url={c.avatar_url} name={c.name} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 id={`cand-${f.id}`} className="text-[14px] font-semibold text-ink-950">{c.name}</h3>
            {f.detection_type && <Badge tone={f.detection_type === "scam_account" ? "crit" : f.detection_type === "lookalike_account" ? "outline" : "high"}>{DETECTION_TYPE_LABELS[f.detection_type] ?? f.detection_type}</Badge>}
            <SourceTypeBadge type={c.source_type} />
            <ChangeBadge state={f.change_state} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-ink-500">
            <span className="inline-flex items-center gap-1.5"><PlatformGlyph platform={c.platform} />{sourceLabel(c.platform)}</span>
            {c.handle && <span className="font-mono text-[11.5px]">@{c.handle}</span>}
            {profile ? (
              <a href={profile} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-teal-700 hover:underline">
                View profile <ExternalLink className="size-3" />
              </a>
            ) : c.source_type === "simulated" ? (
              <span className="text-med">Synthetic — no real profile</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <RiskBadge level={f.risk_level} score={f.risk_score} />
          <StatusBadge status={f.status} level={f.risk_level} />
        </div>
      </div>

      {c.description && (
        <p className={cx("mt-2.5 rounded-md border border-ink-150 bg-white px-3 py-2 text-[12.5px] leading-relaxed whitespace-pre-line text-ink-700", !expanded && "line-clamp-3")}>{c.description}</p>
      )}

      <div className="mt-3 grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-6">
        {SIGNALS.map((s) => <SignalMeter key={s.key} label={s.label} s={f.signal_scores?.[s.key]} />)}
      </div>

      <div className="mt-3 rounded-md bg-ink-50 px-3 py-2.5">
        <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Why flagged?</div>
        <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-800">
          <span className="font-medium">{f.classification}.</span> {f.explanation}
        </p>
        {expanded && (f.reasons?.length ?? 0) > 0 && (
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12px] text-ink-600 marker:text-ink-300">
            {f.reasons!.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        )}
        {expanded && (f.not_evaluated?.length ?? 0) > 0 && (
          <p className="mt-1.5 text-[11.5px] text-ink-500"><span className="font-medium text-ink-600">Not evaluated:</span> {f.not_evaluated!.join(" · ")}</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="min-w-0 text-[11.5px] leading-relaxed text-ink-500">
          Collected {dateTime(c.last_observed_at)}
          {c.first_observed_at !== c.last_observed_at && <> · first seen {relTime(c.first_observed_at)}</>}
          {" · via "}
          <span className="text-ink-700">{c.source === "demo" ? "bundled synthetic dataset" : endpointLabel(prov.endpoint, c.source)}</span>
          {queries.length > 0 && <> · matched {queries.map((q) => `“${q}”`).join(", ")}</>}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>{expanded ? "Less" : "More"}</Button>
          {f.status !== "confirmed" && <Button size="sm" variant="primary" icon={<ShieldX className="size-3.5" />} loading={busy === "confirm"} disabled={!!busy} onClick={() => decide("confirm")}>Confirm</Button>}
          {f.status !== "safe" && <Button size="sm" icon={<ShieldCheck className="size-3.5" />} loading={busy === "mark_safe"} disabled={!!busy} onClick={() => decide("mark_safe")}>Mark legitimate</Button>}
          {(f.status === "confirmed" || f.status === "safe") && <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} loading={busy === "reopen"} disabled={!!busy} onClick={() => decide("reopen")}>Reopen</Button>}
          <Link href={`/app/investigations/${f.id}`} className="inline-flex h-7 items-center gap-1 px-1.5 text-[12.5px] font-medium text-teal-700 hover:underline">
            Investigate <ArrowUpRight className="size-3.5" />
          </Link>
        </div>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- page

export function SocialMonitor() {
  const { selected } = useBrands();
  const { active, startScan, version } = useScans();
  const [platform, setPlatform] = useState<string>("");
  const [levels, setLevels] = useState<string[]>(["critical", "high", "medium"]);
  const [dtype, setDtype] = useState("");
  const [status, setStatus] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sort, setSort] = useState("risk");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(0), [selected?.id, platform, levels, dtype, status, sourceType, sort, debounced]);

  const { data: cfg } = useApi<{ config: { enabled_sources: string[]; mastodon_instances: string[] } }>("/sources");
  const enabledSocial = (cfg?.config.enabled_sources ?? []).filter((s) => (SOCIAL as readonly string[]).includes(s));
  const { data: scans, reload: reloadScans } = useApi<Scan[]>(selected ? "/scans" : null, { brand_id: selected?.id, limit: 30 });
  const query = useMemo(
    () => ({
      brand_id: selected?.id,
      kind: "account",
      level: levels.length ? levels : [...LEVELS],
      source: platform ? [platform] : undefined,
      detection_type: dtype ? [dtype] : undefined,
      status: status ? [status] : undefined,
      source_type: sourceType || undefined,
      q: debounced || undefined,
      sort,
      order: sort === "name" ? "asc" : "desc",
      include_signals: true,
      limit: PAGE,
      offset: page * PAGE,
    }),
    [selected?.id, levels, platform, dtype, status, sourceType, debounced, sort, page],
  );
  const { data, error, loading, reload, setData } = useApi<Paged<Finding>>(selected ? "/findings" : null, query);
  useEffect(() => {
    if (version) {
      reload(true);
      reloadScans(true);
    }
  }, [version, reload, reloadScans]);

  if (!selected) return null;
  const running = active.find((s) => s.brand_id === selected.id);
  const lastSocial = scans?.find((s) => s.status !== "running" && s.status !== "queued" && s.sources.some((x) => (SOCIAL as readonly string[]).includes(x.source) || x.source === "demo"));
  const scanSources = selected.is_demo ? ["demo"] : enabledSocial;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <div className="text-[11.5px] font-medium tracking-wide text-ink-500 uppercase">Monitor</div>
          <h1 className="text-[21px] font-semibold tracking-[-0.02em] text-ink-950">Social Monitoring</h1>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-500">
            Fake profiles, fake brand pages and scam accounts using {selected.name}’s identity on {selected.is_demo ? "synthetic Bluesky/Mastodon data" : "Bluesky, Mastodon and YouTube (when its API key is configured)"}. Official accounts are excluded by exact identifier before scoring. Scans are periodic searches, not a live stream.
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Radar className="size-3.5" />}
          loading={!!running}
          disabled={!!running || scanSources.length === 0}
          onClick={() => startScan(selected.id, scanSources)}
        >
          {running ? `Scanning ${Math.round(running.progress * 100)}%` : selected.is_demo ? "Run demo scan" : `Scan ${scanSources.map(sourceLabel).join(" + ") || "social sources"}`}
        </Button>
      </div>

      {selected.is_demo && (
        <Notice tone="warn" icon={<Info className="size-4" />}>Demo brand: candidates below come from a bundled <strong className="font-medium">synthetic</strong> dataset, run through the real detection engine and labelled “Simulated”. They are never shown for real brands.</Notice>
      )}
      {!selected.is_demo && cfg && enabledSocial.length === 0 && (
        <Notice tone="warn">No social sources are enabled. <Link href="/app/sources" className="font-medium underline">Enable Bluesky or Mastodon</Link> to scan.</Notice>
      )}

      {running ? <WorkflowProgress scan={running} /> : lastSocial ? <ScanSummary scan={lastSocial} /> : scans && (
        <Card><EmptyState icon={<Radar className="size-5" />} title="No social scan yet" description="Run a scan to query the enabled social sources with bounded look-alike searches for this brand." /></Card>
      )}

      <Card className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-150 px-3 py-2.5">
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-400" />
            <Input aria-label="Search candidates" placeholder="Name, handle or ID…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8" />
          </div>
          <Select aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">All platforms</option>
            <option value="bluesky">Bluesky</option>
            <option value="mastodon">Mastodon</option>
            <option value="youtube">YouTube</option>
          </Select>
          <div role="group" aria-label="Risk level" className="flex gap-1">
            {LEVELS.map((l) => {
              const on = levels.includes(l);
              return (
                <button key={l} aria-pressed={on} onClick={() => setLevels((ls) => (on ? ls.filter((x) => x !== l) : [...ls, l]))}
                  className={cx("h-8 rounded-md border px-2.5 text-[12px] font-medium capitalize transition-colors", on ? "border-ink-800 bg-ink-800 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300")}>
                  {l}
                </button>
              );
            })}
          </div>
          <Select aria-label="Detection type" value={dtype} onChange={(e) => setDtype(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">All detection types</option>
            {ACCOUNT_TYPES.map((t) => <option key={t} value={t}>{DETECTION_TYPE_LABELS[t]}</option>)}
          </Select>
          <Select aria-label="Review status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">Any status</option>
            <option value="open">Open</option>
            <option value="escalated">Further review</option>
            <option value="confirmed">Confirmed</option>
            <option value="safe">Marked legitimate</option>
            <option value="resolved">No longer observed</option>
          </Select>
          <Select aria-label="Data type" value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">Live & simulated</option>
            <option value="live">Live only</option>
            <option value="simulated">Simulated only</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="ml-auto h-8 w-auto text-[12.5px]">
            <option value="risk">Sort: highest risk</option>
            <option value="last_seen">Sort: most recently seen</option>
            <option value="first_seen">Sort: newest first seen</option>
            <option value="name">Sort: name A–Z</option>
          </Select>
        </div>
        {error && <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div>}
        {loading && !data ? (
          <div className="space-y-3 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-36" />)}</div>
        ) : data && data.items.length === 0 ? (
          <EmptyState
            icon={<SearchX className="size-5" />}
            title={lastSocial ? "No social candidates match these filters" : "No candidates yet"}
            description={lastSocial ? "Try including lower risk levels or another detection type. Unrelated accounts are not retained." : "Run a scan to collect candidates."}
          />
        ) : (
          <div className="divide-y divide-ink-150">
            {data?.items.map((f) => (
              <CandidateCard key={f.id} f={f} onChange={(nf) => setData({ ...data, items: data.items.map((x) => (x.id === nf.id ? nf : x)) })} />
            ))}
          </div>
        )}
        {data && total > 0 && (
          <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2 text-[12px] text-ink-500">
            <span className="tabular">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total} accounts</span>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="size-3.5" /></Button>
              <span className="tabular px-1">{page + 1} / {pages}</span>
              <Button size="sm" variant="ghost" aria-label="Next page" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="size-3.5" /></Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

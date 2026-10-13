"use client";

import { ArrowUpRight, ChevronLeft, ChevronRight, Download, ExternalLink, Info, Radar, RotateCcw, Search, SearchX, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, buildQuery } from "@/lib/api";
import { dateTime, DETECTION_TYPE_LABELS, relTime, safeHref, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Brand, Finding, OfficialApp, Paged, Scan } from "@/lib/types";
import { useToast } from "../toast";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Notice, Select, Skeleton, cx } from "../ui";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, SourceTypeBadge, StatusBadge } from "./bits";
import { useBrands, useScans } from "./providers";
import { endpointLabel, ScanSummary, SignalMeter, WorkflowProgress } from "./social-monitor";

const STORES = ["apple_app_store", "google_play"] as const;
const LEVELS = ["critical", "high", "medium", "low"] as const;
const APP_TYPES = ["suspicious_app", "lookalike_app", "official_publisher_app"];
const SIGNALS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "package", label: "Package ID" },
  { key: "logo", label: "Icon" },
  { key: "description", label: "Description" },
  { key: "publisher", label: "Publisher" },
  { key: "urls", label: "Links" },
  { key: "scam", label: "Scam cues" },
];
const PAGE = 10;

/** The store's own bundle/package ID (demo and imported records namespace `external_id`). */
function appId(c: Finding["candidate"]): string {
  const m = c.metadata as { bundle_id?: string; package?: string; native_id?: string };
  return m.bundle_id || m.package || m.native_id || c.external_id;
}

/** Candidate store → registry store name. */
const storeOf = (platform: string) => (platform === "apple_app_store" ? "apple" : platform);

function closestOfficial(brand: Brand, platform: string): OfficialApp | undefined {
  const apps = brand.official_apps ?? [];
  return apps.find((a) => a.store === storeOf(platform)) ?? apps[0];
}

type Sig = { score: number; evaluated: boolean; detail: string } | undefined;

function Verdict({ tone, children }: { tone: "same" | "diff" | "warn" | "na"; children: React.ReactNode }) {
  const cls = { same: "text-forest-700", diff: "text-crit", warn: "text-med", na: "text-ink-400" }[tone];
  return <span className={cx("text-[11px] font-medium", cls)}>{children}</span>;
}

function Comparison({ f, brand }: { f: Finding; brand: Brand }) {
  const c = f.candidate;
  const off = closestOfficial(brand, c.platform);
  const s = (k: string): Sig => f.signal_scores?.[k];
  const pct = (x: Sig) => (x?.evaluated ? `${Math.round(x.score * 100)}% similar` : "not evaluated");
  const pub = s("publisher");
  const sameOfficialPub = f.detection_type === "official_publisher_app";
  const crossStore = off && off.store !== storeOf(c.platform);
  const rows: { label: string; official: React.ReactNode; candidate: React.ReactNode; verdict: React.ReactNode }[] = [
    {
      label: "App name",
      official: off?.name || brand.name,
      candidate: c.name,
      verdict: <Verdict tone={(s("name")?.score ?? 0) >= 0.7 ? "warn" : "na"}>{pct(s("name"))}</Verdict>,
    },
    {
      label: "Developer",
      official: off?.publisher_name || <span className="text-ink-400">not on file</span>,
      candidate: c.publisher_name || <span className="text-ink-400">not listed</span>,
      verdict: sameOfficialPub ? <Verdict tone="same">Official developer ID</Verdict> : pub?.evaluated ? <Verdict tone={pub.score >= 0.75 ? "diff" : "warn"}>Different developer</Verdict> : <Verdict tone="na">Cannot verify</Verdict>,
    },
    {
      label: "Developer ID",
      official: off?.publisher_id ? <code className="font-mono text-[11px]">{off.publisher_id}</code> : <span className="text-ink-400">not on file</span>,
      candidate: c.publisher_id ? <code className="font-mono text-[11px]">{c.publisher_id}</code> : <span className="text-ink-400">not exposed</span>,
      verdict: sameOfficialPub ? <Verdict tone="same">Match</Verdict> : off?.publisher_id && c.publisher_id ? <Verdict tone="diff">Differs</Verdict> : <Verdict tone="na">—</Verdict>,
    },
    {
      label: "Bundle / package ID",
      official: off ? <code className="font-mono text-[11px] break-all">{off.app_id}</code> : <span className="text-ink-400">none registered</span>,
      candidate: <code className="font-mono text-[11px] break-all">{appId(c)}</code>,
      verdict: <Verdict tone="diff">Not on allowlist</Verdict>,
    },
    {
      label: "Icon",
      official: brand.has_logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/api/brands/${brand.id}/logo?v=${brand.logo_phash}`} alt={`${brand.name} logo`} className="size-9 rounded-[22%] border border-ink-150 bg-white object-contain" />
      ) : <span className="text-ink-400">no brand logo</span>,
      candidate: <Avatar url={c.avatar_url} name={c.name} size={36} square />,
      verdict: <Verdict tone={(s("logo")?.score ?? 0) >= 0.75 ? "diff" : "na"}>{pct(s("logo"))}</Verdict>,
    },
    {
      label: "Description",
      official: <span className="text-ink-500">brand profile & official listings</span>,
      candidate: <span className="text-ink-500">{c.description ? `${c.description.length} chars` : "empty"}</span>,
      verdict: <Verdict tone={(s("description")?.score ?? 0) >= 0.3 ? "diff" : "na"}>{pct(s("description"))}</Verdict>,
    },
  ];
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-ink-150">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-150 bg-ink-50 px-3 py-1.5 text-[11px] text-ink-500">
        <span className="font-medium tracking-wide uppercase">Official vs candidate</span>
        {off ? <span>Compared with official {sourceLabel(off.store)} app{crossStore ? " (no official app registered on this store)" : ""}</span> : (
          <Link href={`/app/brands/${brand.id}`} className="text-teal-700 hover:underline">No official apps registered — add them</Link>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-[12px]">
          <thead className="text-[10.5px] text-ink-500 uppercase">
            <tr><th className="px-3 py-1.5 font-medium" scope="col">Field</th><th className="px-3 py-1.5 font-medium" scope="col">Official</th><th className="px-3 py-1.5 font-medium" scope="col">Candidate</th><th className="px-3 py-1.5 font-medium" scope="col">Comparison</th></tr>
          </thead>
          <tbody className="divide-y divide-ink-150">
            {rows.map((r) => (
              <tr key={r.label} className="align-middle">
                <th scope="row" className="px-3 py-1.5 font-normal whitespace-nowrap text-ink-500">{r.label}</th>
                <td className="px-3 py-1.5 text-ink-800">{r.official}</td>
                <td className="px-3 py-1.5 text-ink-900">{r.candidate}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{r.verdict}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ListingFacts({ m }: { m: Record<string, unknown> }) {
  const facts: [string, unknown][] = [
    ["Category", m.genre],
    ["Rating", typeof m.rating === "number" ? `${(m.rating as number).toFixed(1)}${m.rating_count ? ` (${Number(m.rating_count).toLocaleString()})` : ""}` : null],
    ["Installs", m.installs],
    ["Price", m.price ?? (m.free === true ? "Free" : m.free === false ? "Paid" : null)],
    ["Version", m.version],
    ["Updated", typeof m.updated === "string" ? dateTime(m.updated as string) : null],
    ["Seller", m.seller_name],
    ["Store region", typeof m.country === "string" ? (m.country as string).toUpperCase() : null],
  ];
  const shown = facts.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-0.5 text-[11.5px]">
      {shown.map(([k, v]) => (
        <div key={k} className="flex gap-1"><dt className="text-ink-500">{k}</dt><dd className="text-ink-800">{String(v)}</dd></div>
      ))}
    </dl>
  );
}

function AppCard({ f, brand, onChange }: { f: Finding; brand: Brand; onChange: (f: Finding) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const c = f.candidate;
  const listing = c.source_type === "simulated" ? undefined : safeHref(c.url);
  const prov = c.provenance as { endpoint?: string; query?: string; queries?: string[] };
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
    <article className="px-4 py-4" aria-labelledby={`app-${f.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <Avatar url={c.avatar_url} name={c.name} size={48} square />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 id={`app-${f.id}`} className="text-[14px] font-semibold text-ink-950">{c.name}</h3>
            {f.detection_type && <Badge tone={f.detection_type === "suspicious_app" ? "high" : "outline"}>{DETECTION_TYPE_LABELS[f.detection_type] ?? f.detection_type}</Badge>}
            <SourceTypeBadge type={c.source_type} />
            <ChangeBadge state={f.change_state} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-ink-500">
            <span className="inline-flex items-center gap-1.5"><PlatformGlyph platform={c.platform} />{sourceLabel(c.platform)}</span>
            <span>by <span className="text-ink-700">{c.publisher_name || "unknown developer"}</span>{c.publisher_id && <span className="font-mono text-[11px]"> · ID {c.publisher_id}</span>}</span>
            <code className="font-mono text-[11px] break-all">{appId(c)}</code>
            {listing ? (
              <a href={listing} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-teal-700 hover:underline">
                View listing <ExternalLink className="size-3" />
              </a>
            ) : c.source_type === "simulated" ? <span className="text-med">Synthetic — no real listing</span> : null}
          </div>
          <ListingFacts m={c.metadata} />
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <RiskBadge level={f.risk_level} score={f.risk_score} />
          <StatusBadge status={f.status} level={f.risk_level} />
        </div>
      </div>

      {c.description && (
        <p className={cx("mt-2.5 rounded-md border border-ink-150 bg-white px-3 py-2 text-[12.5px] leading-relaxed whitespace-pre-line text-ink-700", !expanded && "line-clamp-3")}>{c.description}</p>
      )}

      <div className="mt-3 grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-7">
        {SIGNALS.map((s) => <SignalMeter key={s.key} label={s.label} s={f.signal_scores?.[s.key]} />)}
      </div>

      {expanded && <Comparison f={f} brand={brand} />}

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
          Retrieved {dateTime(c.last_observed_at)}
          {c.first_observed_at !== c.last_observed_at && <> · first seen {relTime(c.first_observed_at)}</>}
          {" · via "}
          <span className="text-ink-700">{c.source === "demo" ? "bundled synthetic dataset" : c.source === "google_play" ? "google-play-scraper (unofficial)" : endpointLabel(prov.endpoint, c.source)}</span>
          {queries.length > 0 && <> · matched {queries.map((q) => `“${q}”`).join(", ")}</>}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>{expanded ? "Hide comparison" : "Compare with official"}</Button>
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

export function AppMonitor() {
  const { selected } = useBrands();
  const { active, startScan, version } = useScans();
  const [store, setStore] = useState("");
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
  useEffect(() => setPage(0), [selected?.id, store, levels, dtype, status, sourceType, sort, debounced]);

  const { data: cfg } = useApi<{ config: { enabled_sources: string[] } }>("/sources");
  const enabledStores = (cfg?.config.enabled_sources ?? []).filter((s) => (STORES as readonly string[]).includes(s));
  const { data: scans, reload: reloadScans } = useApi<Scan[]>(selected ? "/scans" : null, { brand_id: selected?.id, limit: 30 });
  const filters = useMemo(
    () => ({
      brand_id: selected?.id,
      kind: "app",
      level: levels.length ? levels : [...LEVELS],
      source: store ? [store] : undefined,
      detection_type: dtype ? [dtype] : undefined,
      status: status ? [status] : undefined,
      source_type: sourceType || undefined,
      q: debounced || undefined,
    }),
    [selected?.id, levels, store, dtype, status, sourceType, debounced],
  );
  const query = useMemo(
    () => ({ ...filters, sort, order: sort === "name" ? "asc" : "desc", include_signals: true, limit: PAGE, offset: page * PAGE }),
    [filters, sort, page],
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
  const lastApp = scans?.find((s) => s.status !== "running" && s.status !== "queued" && s.sources.some((x) => (STORES as readonly string[]).includes(x.source) || x.source === "demo"));
  const scanSources = selected.is_demo ? ["demo"] : enabledStores;
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const exportHref = `/api/findings/export.csv${buildQuery(filters)}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <div className="text-[11.5px] font-medium tracking-wide text-ink-500 uppercase">Monitor</div>
          <h1 className="text-[21px] font-semibold tracking-[-0.02em] text-ink-950">App Store Monitoring</h1>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-500">
            Mobile apps that reuse {selected.name}’s name, icon or description under another developer on {selected.is_demo ? "synthetic App Store/Google Play data" : "the Apple App Store and Google Play"}. Official apps are excluded by exact bundle/package ID before scoring. A different developer or package ID alone is never enough to rate an app above low.
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Radar className="size-3.5" />}
          loading={!!running}
          disabled={!!running || scanSources.length === 0}
          onClick={() => startScan(selected.id, scanSources)}
        >
          {running ? `Scanning ${Math.round(running.progress * 100)}%` : selected.is_demo ? "Run demo scan" : "Scan now"}
        </Button>
      </div>

      {selected.is_demo && (
        <Notice tone="warn" icon={<Info className="size-4" />}>Demo brand: app listings below come from a bundled <strong className="font-medium">synthetic</strong> dataset, run through the real detection engine and labelled “Simulated”. They are never shown for real brands.</Notice>
      )}
      {!selected.is_demo && cfg && enabledStores.length === 0 && (
        <Notice tone="warn">No app stores are enabled. <Link href="/app/sources" className="font-medium underline">Enable the App Store or Google Play</Link> to scan.</Notice>
      )}
      {!selected.is_demo && (selected.official_apps?.length ?? 0) === 0 && (
        <Notice tone="teal" icon={<Info className="size-4" />}>
          No official apps are registered for {selected.name}, so official listings can’t be excluded and developer IDs can’t be verified. <Link href={`/app/brands/${selected.id}`} className="font-medium underline">Add official apps</Link>.
        </Notice>
      )}

      <div className="grid gap-2 text-[11.5px] text-ink-500 sm:grid-cols-2">
        <p><span className="font-medium text-ink-700">App Store</span> — Apple’s public iTunes Search API (official, unauthenticated). Apple asks for about 20 requests/minute; 403/429 is reported as rate limited.</p>
        <p><span className="font-medium text-ink-700">Google Play</span> — the open-source google-play-scraper, which parses public store pages. <strong className="font-medium text-med">Not an official Google API</strong>; it can break or be rate-limited without notice. Details are cached for 6 hours.</p>
      </div>

      {running ? <WorkflowProgress scan={running} /> : lastApp ? <ScanSummary scan={lastApp} include={STORES} title="Last app scan" /> : scans && (
        <Card><EmptyState icon={<Radar className="size-5" />} title="No app scan yet" description="Run a scan to search the enabled app stores with bounded look-alike queries for this brand." /></Card>
      )}

      <Card className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-150 px-3 py-2.5">
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-400" />
            <Input aria-label="Search apps" placeholder="App name or package ID…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8" />
          </div>
          <Select aria-label="Store" value={store} onChange={(e) => setStore(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">All stores</option>
            <option value="apple_app_store">App Store</option>
            <option value="google_play">Google Play</option>
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
            {APP_TYPES.map((t) => <option key={t} value={t}>{DETECTION_TYPE_LABELS[t]}</option>)}
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
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="risk">Sort: highest risk</option>
            <option value="last_seen">Sort: most recently retrieved</option>
            <option value="first_seen">Sort: newest first seen</option>
            <option value="name">Sort: name A–Z</option>
          </Select>
          <a href={exportHref} download className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-md border border-ink-200 bg-white px-2.5 text-[12.5px] font-medium text-ink-700 hover:border-ink-300">
            <Download className="size-3.5" /> Export CSV
          </a>
        </div>
        {error && <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div>}
        {loading && !data ? (
          <div className="space-y-3 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)}</div>
        ) : data && data.items.length === 0 ? (
          <EmptyState
            icon={<SearchX className="size-5" />}
            title={lastApp ? "No app listings match these filters" : "No app candidates yet"}
            description={lastApp ? "Try including low risk or another detection type. Unrelated apps and official apps are not shown." : "Run a scan to collect app listings."}
          />
        ) : (
          <div className="divide-y divide-ink-150">
            {data?.items.map((f) => (
              <AppCard key={f.id} f={f} brand={selected} onChange={(nf) => setData({ ...data, items: data.items.map((x) => (x.id === nf.id ? nf : x)) })} />
            ))}
          </div>
        )}
        {data && total > 0 && (
          <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2 text-[12px] text-ink-500">
            <span className="tabular">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total} apps</span>
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

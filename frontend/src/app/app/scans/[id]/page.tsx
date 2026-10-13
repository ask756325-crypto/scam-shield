"use client";

import { ArrowLeft, CalendarClock, ShieldCheck } from "lucide-react";
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useBrands } from "@/components/app/providers";
import { Avatar, RiskBadge, StatusBadge, StatusDot, SOURCE_STATUS_LABEL } from "@/components/app/bits";
import { Badge, Button, Card, CardHeader, ErrorState, Notice, PageHeader, ProgressBar, Segmented, Skeleton } from "@/components/ui";
import { dateTime, duration, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ChangeKind, Scan, ScanChange } from "@/lib/types";

const CHANGE_LABEL: Record<ChangeKind, string> = {
  new: "New", changed: "Changed", recurring: "Recurring", reappeared: "Reappeared", missing: "Missing", resolved: "Resolved", unverified: "Unverified",
};
const CHANGE_HELP: Record<ChangeKind, string> = {
  new: "First observed in this scan.",
  changed: "Observed again with different metadata or risk level.",
  recurring: "Observed again without material changes.",
  reappeared: "Observed again after being missing or resolved; resolved findings reopen.",
  missing: "Not returned although its source completed cleanly. Resolved only if consecutive clean scans also miss it.",
  resolved: "Absent from the required number of consecutive clean scans of its source — no longer observed.",
  unverified: "Its source failed or returned incomplete results in this scan, so absence is unknown. Nothing was resolved.",
};
const FIELD_LABEL: Record<string, string> = {
  name: "Name", handle: "Handle", url: "URL", description: "Description", avatar_url: "Avatar / icon", publisher_name: "Publisher", publisher_id: "Publisher ID", external_links: "Links",
};

function show(v: unknown) {
  if (v === null || v === undefined || v === "") return "—";
  return Array.isArray(v) ? (v.length ? v.join(", ") : "—") : String(v);
}

function Changes({ scanId }: { scanId: number }) {
  const [kind, setKind] = useState<ChangeKind | "all">("all");
  const { data } = useApi<{ counts: Record<ChangeKind, number>; items: ScanChange[] }>(`/scans/${scanId}/changes`, { change: kind === "all" ? undefined : [kind], limit: 500 });
  const counts = data?.counts;
  const kinds = (Object.keys(CHANGE_LABEL) as ChangeKind[]).filter((k) => (counts?.[k] ?? 0) > 0);
  return (
    <Card>
      <CardHeader title="Changes in this scan" description="What this scan concluded about each finding, compared with earlier observations." />
      {counts && kinds.length > 0 && (
        <div className="border-b border-ink-150 px-4 py-2.5">
          <Segmented<ChangeKind | "all">
            label="Change type"
            value={kind}
            onChange={setKind}
            options={[{ value: "all", label: "All", count: Object.values(counts).reduce((a, b) => a + b, 0) }, ...kinds.map((k) => ({ value: k, label: CHANGE_LABEL[k], count: counts[k] }))]}
          />
          {kind !== "all" && <p className="mt-1.5 text-[11.5px] text-ink-500">{CHANGE_HELP[kind]}</p>}
        </div>
      )}
      {!data ? (
        <div className="p-4"><Skeleton className="h-16" /></div>
      ) : data.items.length === 0 ? (
        <p className="px-4 py-3 text-[12.5px] text-ink-400">No findings were created or updated by this scan.</p>
      ) : (
        <ul className="divide-y divide-ink-150">
          {data.items.map((c, i) => (
            <li key={`${c.finding.id}-${i}`} className="px-4 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
                <Badge tone={c.change === "new" ? "teal" : c.change === "changed" || c.change === "reappeared" ? "high" : c.change === "resolved" ? "forest" : c.change === "unverified" ? "med" : "outline"} title={CHANGE_HELP[c.change]}>
                  {CHANGE_LABEL[c.change]}
                </Badge>
                <Avatar url={c.candidate.avatar_url} name={c.candidate.name} size={22} square={c.candidate.kind === "app"} />
                <Link href={`/app/investigations/${c.finding.id}`} className="font-medium text-teal-700 hover:underline">{c.candidate.name}</Link>
                <span className="text-ink-500">{sourceLabel(c.candidate.platform)}{c.candidate.handle ? ` · @${c.candidate.handle}` : ""}</span>
                <RiskBadge level={c.finding.risk_level} score={c.finding.risk_score} />
                {c.risk_before && c.risk_after && c.risk_before !== c.risk_after && <span className="text-[11.5px] text-ink-500">risk {c.risk_before} → {c.risk_after}</span>}
                {(c.change === "missing" || c.change === "resolved" || c.change === "reappeared") && c.missed_scans > 0 && (
                  <span className="text-[11.5px] text-ink-500">{c.change === "reappeared" ? "after " : ""}{c.missed_scans} clean miss{c.missed_scans > 1 ? "es" : ""}</span>
                )}
                <span className="ml-auto"><StatusBadge status={c.finding.status} level={c.finding.risk_level} /></span>
              </div>
              {c.changed_fields.length > 0 && (
                <dl className="mt-1.5 ml-1 space-y-1 border-l-2 border-ink-150 pl-3 text-[12px]">
                  {c.changed_fields.map((f) => (
                    <div key={f}>
                      <dt className="text-ink-500">{FIELD_LABEL[f] ?? f}</dt>
                      <dd className="break-words"><span className="text-ink-400 line-through">{show(c.previous[f])}</span> <span className="text-ink-400">→</span> <span className="text-ink-900">{show(c.current[f])}</span></dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

interface ExclusionRow { id: number; scan_id: number; source: string; external_id: string; name: string; url: string | null; rule: string; matched_value: string; created_at: string }

export default function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { select } = useBrands();
  const { data: first } = useApi<Scan>(`/scans/${id}`);
  const running = !first || first.status === "running" || first.status === "queued";
  const { data: polled, error } = useApi<Scan>(`/scans/${id}`, undefined, { pollMs: running ? 1000 : undefined });
  const s = polled ?? first;
  const { data: exclusions } = useApi<ExclusionRow[]>(s && !running ? `/brands/${s.brand_id}/exclusions` : null, { limit: 500 });
  const mine = exclusions?.filter((e) => e.scan_id === s?.id) ?? [];

  if (error) return <ErrorState error={error} />;
  if (!s) return <Skeleton className="h-80" />;
  const live = s.status === "running" || s.status === "queued";

  return (
    <div className="animate-fade-in space-y-4">
      <Link href="/app/scans" className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-500 hover:text-ink-900">
        <ArrowLeft className="size-3.5" /> Scan history
      </Link>
      <PageHeader
        eyebrow={<span className="inline-flex items-center gap-1.5">{s.brand_name} · {s.trigger === "scheduled" && <CalendarClock className="size-3" />}{s.trigger} scan</span>}
        title={
          <span className="inline-flex items-center gap-2.5">
            Scan #{s.id}
            <span className="inline-flex items-center gap-1.5 text-[13px] font-medium capitalize text-ink-600"><StatusDot status={s.status} /> {s.status}</span>
            {s.mode === "demo" && <Badge tone="med">Synthetic data</Badge>}
            {s.mode === "import" && <Badge tone="outline">CSV import</Badge>}
          </span>
        }
        description={`Started ${dateTime(s.started_at ?? s.created_at)}${s.finished_at ? ` · finished ${dateTime(s.finished_at)}` : ""}${s.duration_ms != null ? ` · ${duration(s.duration_ms)}` : ""}${s.trigger === "scheduled" ? " · started by the scheduler" : ""}`}
        actions={!live && <Button onClick={() => { select(s.brand_id); router.push("/app/investigations"); }}>View {s.brand_name} findings</Button>}
      />
      {live && (
        <Card className="p-4">
          <div className="mb-2 flex justify-between text-[12.5px]"><span className="text-ink-700">{s.stage}</span><span className="tabular text-ink-500">{Math.round(s.progress * 100)}%</span></div>
          <ProgressBar value={s.progress} />
          <p className="mt-2 text-[11.5px] text-ink-500">Progress counts completed source queries plus logo comparison and scoring stages. Sources are searched periodically, not streamed.</p>
        </Card>
      )}
      {s.error && <Notice tone="warn">{s.error}</Notice>}

      <Card className="grid grid-cols-2 divide-ink-150 sm:grid-cols-5 lg:grid-cols-10 lg:divide-x">
        {[
          ["Collected", s.candidates_collected],
          ["Unique", s.candidates_unique],
          ["Official excluded", s.excluded_official],
          ["New", s.findings_new],
          ["Changed", s.findings_changed],
          ["Recurring", s.findings_recurring],
          ["Missing", s.findings_missing ?? 0],
          ["Resolved", s.findings_resolved],
          ["Unverified", s.findings_unverified ?? 0],
          ["Source failures", s.source_failures?.length ?? 0],
        ].map(([l, v]) => (
          <div key={l as string} className="px-4 py-3">
            <div className="text-[11.5px] text-ink-500">{l}</div>
            <div className="tabular mt-1 text-[20px] font-semibold text-ink-950">{v}</div>
          </div>
        ))}
      </Card>

      <Card>
        <CardHeader title="Per-source results" description="Each source runs independently; a failure in one never stops the others." />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[12.5px]">
            <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
              <tr>
                <th className="py-2 pr-3 pl-4 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Queries</th>
                <th className="px-3 py-2 text-right font-medium">Failed</th>
                <th className="px-3 py-2 text-right font-medium">Candidates</th>
                <th className="px-3 py-2 text-right font-medium">Duration</th>
                <th className="py-2 pr-4 pl-3 font-medium">Errors</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-150">
              {s.sources.map((x) => (
                <tr key={x.source}>
                  <td className="py-2.5 pr-3 pl-4 font-medium text-ink-900">{sourceLabel(x.source)}</td>
                  <td className="px-3 py-2.5"><span className="inline-flex items-center gap-1.5"><StatusDot status={x.status} /> {SOURCE_STATUS_LABEL[x.status] ?? x.status}</span></td>
                  <td className="tabular px-3 py-2.5 text-right">{x.queries_done}/{x.queries_total}</td>
                  <td className="tabular px-3 py-2.5 text-right text-ink-600">{x.queries_failed}</td>
                  <td className="tabular px-3 py-2.5 text-right">{x.candidates}</td>
                  <td className="tabular px-3 py-2.5 text-right text-ink-600">{duration(x.duration_ms)}</td>
                  <td className="max-w-[360px] py-2.5 pr-4 pl-3 text-[11.5px] text-ink-600">{x.error ?? <span className="text-ink-400">None</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {!live && <Changes scanId={s.id} />}
      {!live && (s.findings_unverified ?? 0) > 0 && (
        <Notice tone="warn">
          {s.findings_unverified} finding{s.findings_unverified === 1 ? "" : "s"} could not be checked because {s.source_failures?.length ? s.source_failures.map(sourceLabel).join(", ") : "a source"} failed or returned incomplete results. Missing data is not treated as resolution.
        </Notice>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr] [&>*]:min-w-0">
        <Card>
          <CardHeader title="Search terms" description="Bounded look-alike queries from brand names and aliases" />
          <div className="flex flex-wrap gap-1.5 px-4 py-3">
            {s.search_terms.map((t) => <code key={t} className="rounded-[4px] border border-ink-150 bg-white px-1.5 py-0.5 font-mono text-[11.5px] text-ink-700">{t}</code>)}
            {!s.search_terms.length && <span className="text-[12px] text-ink-400">—</span>}
          </div>
        </Card>
        <Card>
          <CardHeader title="Official assets excluded in this scan" description="Matched before scoring by exact identifiers — audit trail" />
          {mine.length ? (
            <ul className="divide-y divide-ink-150">
              {mine.map((e) => (
                <li key={e.id} className="flex items-center gap-3 px-4 py-2 text-[12.5px]">
                  <ShieldCheck className="size-4 shrink-0 text-forest-600" />
                  <span className="min-w-0 flex-1 truncate text-ink-900">{e.name} <span className="text-ink-500">· {sourceLabel(e.source)}</span></span>
                  <code className="truncate font-mono text-[11px] text-ink-500" title={e.matched_value}>{e.rule}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-3 text-[12.5px] text-ink-400">{live ? "Available when the scan finishes." : "No official assets appeared in this scan’s results."}</p>
          )}
        </Card>
      </div>
    </div>
  );
}

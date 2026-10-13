"use client";

import { ArrowLeft, Check, ChevronDown, Download, ExternalLink, Flag, Link2, MessageSquarePlus, RotateCcw, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, ScoreMeter, SourceTypeBadge, StatusBadge } from "@/components/app/bits";
import { useBrands } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Dialog, ErrorState, Kbd, Skeleton, Textarea, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, DETECTION_TYPE_LABELS, relTime, safeHref, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Evidence, Finding, FindingStatus, Inference, RelatedGroup } from "@/lib/types";

type Action = "confirm" | "mark_safe" | "escalate" | "reopen" | "note";

const ACTION_LABEL: Record<string, string> = {
  confirm: "Confirmed impersonation",
  mark_safe: "Marked legitimate",
  escalate: "Marked for further review",
  reopen: "Reopened",
  note: "Note",
};
const STATUS_LABEL: Record<FindingStatus, string> = {
  open: "Needs review",
  escalated: "Further review",
  confirmed: "Confirmed",
  safe: "Legitimate",
  resolved: "No longer observed",
};
// Which actions each status allows (mirrors the API's transition rules).
const ALLOWED: Record<FindingStatus, Action[]> = {
  open: ["confirm", "mark_safe", "escalate"],
  escalated: ["confirm", "mark_safe", "reopen"],
  confirmed: ["mark_safe", "reopen"],
  safe: ["confirm", "reopen"],
  resolved: ["confirm", "mark_safe", "escalate", "reopen"],
};
const DIALOG: Record<Exclude<Action, "reopen">, { title: string; description: string; placeholder: string }> = {
  confirm: {
    title: "Confirm impersonation",
    description: "Records your decision that this is an impersonation. ScamShield does not file takedown requests automatically.",
    placeholder: "Optional note — e.g. evidence, ticket number",
  },
  mark_safe: {
    title: "Mark as legitimate",
    description: "Removes it from the review queue. It reopens automatically if the listing changes.",
    placeholder: "Optional note — e.g. licensed partner, fan account",
  },
  escalate: {
    title: "Mark for further review",
    description: "Keeps it in the review queue, flagged for a second look (e.g. by the brand or legal team).",
    placeholder: "What still needs checking?",
  },
  note: { title: "Add an investigation note", description: "Notes are visible to everyone in your organization and kept in the audit trail.", placeholder: "What did you find?" },
};

function Row({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[minmax(110px,150px)_1fr] gap-3 py-1.5 text-[12.5px]">
      <dt className="text-ink-500">{label}</dt>
      <dd className={cx("min-w-0 break-words text-ink-900", mono && "font-mono text-[11.5px]")}>{children ?? "—"}</dd>
    </div>
  );
}

function SectionLabel({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <h2 className="text-[11px] font-semibold tracking-wide text-ink-500 uppercase">{children}</h2>
      {hint && <span className="text-[11px] text-ink-400">{hint}</span>}
    </div>
  );
}

function InferenceGroups({ items, notEvaluated }: { items: Inference[]; notEvaluated: string[] }) {
  const groups = items.reduce<Record<string, Inference[]>>((acc, x) => ((acc[x.group] ??= []).push(x), acc), {});
  return (
    <Card>
      <CardHeader title="Heuristic inferences" description="Automated similarity and pattern signals computed when the record was scored. Correlated signals share a group; each group counts once." />
      <div className="divide-y divide-ink-150">
        {Object.entries(groups).map(([g, xs]) => {
          const best = xs.filter((x) => x.evaluated).reduce<number | null>((m, x) => (m === null || x.score > m ? x.score : m), null);
          const corroborates = xs.some((x) => x.corroborates);
          return (
            <div key={g} className="px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-[13px] font-medium text-ink-900">
                  {xs[0].group_label}
                  {corroborates && <Badge tone="forest"><Check className="size-3" /> Corroborates</Badge>}
                </div>
                <ScoreMeter value={best ?? 0} evaluated={best !== null} />
              </div>
              <ul className="mt-2 space-y-1.5">
                {xs.map((x) => (
                  <li key={x.signal} className="text-[12px]">
                    <div className="flex gap-2">
                      <span className="w-32 shrink-0 text-ink-500">{x.label}</span>
                      <span className={cx("min-w-0", x.evaluated ? "text-ink-800" : "text-ink-400 italic")}>{x.statement || (x.evaluated ? "" : "Not evaluated")}</span>
                    </div>
                    {x.evidence.length > 0 && (
                      <ul className="mt-1 ml-34 list-disc space-y-0.5 pl-4 text-ink-600 marker:text-ink-300">
                        {x.evidence.map((e, i) => <li key={i}>{e}</li>)}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      {notEvaluated.length > 0 && (
        <div className="border-t border-ink-150 bg-ink-50/60 px-4 py-2.5 text-[11.5px] text-ink-500">
          <span className="font-medium text-ink-700">Not evaluated: </span>
          {notEvaluated.join(" · ")}
        </div>
      )}
    </Card>
  );
}

function SharedIndicators({ id, ev }: { id: string; ev: Evidence }) {
  const { data, error, loading } = useApi<{ groups: RelatedGroup[]; note: string }>(`/findings/${id}/related`);
  return (
    <Card>
      <CardHeader
        title="Shared observable indicators"
        description="Values this record shares with other findings in your organization. An overlap is an observation — it does not by itself show common ownership or a coordinated campaign."
      />
      <div className="px-4 py-3">
        {ev.indicators.length === 0 ? (
          <p className="text-[12.5px] text-ink-400">No comparable indicators (links, contacts, handles or developer IDs) in this record.</p>
        ) : (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {ev.indicators.map((i) => (
              <span key={i.kind + i.value} className="inline-flex max-w-full items-center gap-1 rounded border border-ink-150 bg-white px-1.5 py-0.5 text-[11px] text-ink-600" title={`${i.label.replace("Same ", "")} · from ${i.field}`}>
                <span className="text-ink-400">{i.kind.replace("_", " ")}</span>
                <code className="truncate font-mono text-ink-800">{i.value}</code>
              </span>
            ))}
          </div>
        )}
        {error && <ErrorState error={error} />}
        {loading && !data ? <Skeleton className="h-12" /> : data && ev.indicators.length > 0 && (
          data.groups.length === 0 ? (
            <p className="text-[12.5px] text-ink-500">None of these values appear in any other finding.</p>
          ) : (
            <ul className="space-y-3">
              {data.groups.map((g) => (
                <li key={g.kind + g.value}>
                  <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
                    <Link2 className="size-3.5 text-ink-400" />
                    <span className="font-medium text-ink-900">{g.label}</span>
                    <code className="rounded bg-ink-50 px-1.5 py-px font-mono text-[11.5px] break-all text-ink-800">{g.value}</code>
                    <span className="text-[11.5px] text-ink-500">· {g.count} other finding{g.count === 1 ? "" : "s"}</span>
                  </div>
                  <ul className="mt-1.5 ml-5 space-y-1">
                    {g.candidates.map((m) => (
                      <li key={m.finding_id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px]">
                        <Link href={`/app/investigations/${m.finding_id}`} className="font-medium text-teal-700 hover:underline">{m.name}</Link>
                        <span className="inline-flex items-center gap-1 text-ink-500"><PlatformGlyph platform={m.platform} />{sourceLabel(m.platform)}</span>
                        <RiskBadge level={m.risk_level} />
                        <span className="text-ink-400">{STATUS_LABEL[m.status] ?? m.status} · {m.brand_name}{m.source_type === "simulated" ? " · synthetic" : ""}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
    </Card>
  );
}

export default function FindingPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { reloadBrands } = useBrands();
  const { data: f, error, loading, setData } = useApi<Finding>(`/findings/${id}`);
  const [dialog, setDialog] = useState<Exclude<Action, "reopen"> | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const decide = async (action: Action, text = "") => {
    setBusy(true);
    try {
      const updated = await api<Finding>(`/findings/${id}/decision`, { method: "POST", body: { action, note: text } });
      setData({ ...f!, ...updated });
      toast({ tone: "success", title: action === "note" ? "Note added" : ACTION_LABEL[action] });
      reloadBrands();
      setDialog(null);
      setNote("");
    } catch (e) {
      toast({ tone: "error", title: "Could not save", description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorState error={error} />;
  if (loading || !f) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-72" /></div>;

  const c = f.candidate;
  const ev = f.evidence;
  const sig = f.signals?.signals ?? {};
  const urlScores = (sig.urls?.data?.per_url as Record<string, number> | undefined) ?? {};
  const synthetic = c.source_type === "simulated";
  // Synthetic records carry illustrative URLs that could collide with real profiles — never link them.
  const externalUrl = synthetic ? undefined : safeHref(c.url);
  const allowed = ALLOWED[f.status] ?? [];
  const cmp = ev?.comparison;
  const pv = ev?.provenance;

  return (
    <div className="animate-fade-in space-y-4">
      <Link href="/app/investigations" className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-500 hover:text-ink-900">
        <ArrowLeft className="size-3.5" /> Investigations
      </Link>

      {/* ------------------------------------------------ the finding */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start gap-4">
          <Avatar url={c.avatar_url} name={c.name} size={56} square={c.kind === "app"} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[20px] font-semibold tracking-[-0.02em] text-ink-950">{c.name}</h1>
              <SourceTypeBadge type={c.source_type} />
              <ChangeBadge state={f.change_state} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-500">
              <span className="inline-flex items-center gap-1.5"><PlatformGlyph platform={c.platform} /> {sourceLabel(c.platform)} {c.kind === "app" ? "listing" : "account"}</span>
              {c.handle && <span>@{c.handle}</span>}
              {c.publisher_name && <span>by {c.publisher_name}</span>}
              <span>Brand: <span className="text-ink-800">{f.brand_name}</span></span>
              {externalUrl && (
                <a href={externalUrl} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-teal-700 hover:underline">
                  Open at source <ExternalLink className="size-3" />
                </a>
              )}
              {synthetic && <span className="text-med">Synthetic record — no real profile to open</span>}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <RiskBadge level={f.risk_level} score={f.risk_score} />
              <span className="text-[13px] font-medium text-ink-900">{f.classification}</span>
              {f.detection_type && f.detection_type !== "unrelated" && <Badge tone="outline">{DETECTION_TYPE_LABELS[f.detection_type] ?? f.detection_type}</Badge>}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusBadge status={f.status} level={f.risk_level} />
            <div className="flex flex-wrap justify-end gap-2">
              {allowed.includes("confirm") && <Button variant="primary" size="sm" icon={<ShieldX className="size-3.5" />} disabled={busy} onClick={() => setDialog("confirm")}>Confirm impersonation</Button>}
              {allowed.includes("mark_safe") && <Button size="sm" icon={<ShieldCheck className="size-3.5" />} disabled={busy} onClick={() => setDialog("mark_safe")}>Mark legitimate</Button>}
              {allowed.includes("escalate") && <Button size="sm" icon={<Flag className="size-3.5" />} disabled={busy} onClick={() => setDialog("escalate")}>Further review</Button>}
              {allowed.includes("reopen") && <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} loading={busy} onClick={() => decide("reopen")}>Reopen</Button>}
              <Button size="sm" variant="ghost" icon={<MessageSquarePlus className="size-3.5" />} onClick={() => setDialog("note")}>Add note</Button>
              <details className="relative">
                <summary className="inline-flex h-7 cursor-pointer list-none items-center gap-1 rounded-md px-2 text-[12.5px] font-medium text-ink-700 hover:bg-ink-50 [&::-webkit-details-marker]:hidden">
                  <Download className="size-3.5" /> Export report <ChevronDown className="size-3" />
                </summary>
                <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-ink-150 bg-white p-1 shadow-lg">
                  <a href={`/api/findings/${f.id}/report`} download className="block rounded px-2.5 py-1.5 text-[12.5px] text-ink-800 hover:bg-ink-50">Evidence report (HTML)<span className="block text-[11px] text-ink-500">Readable; print to PDF from a browser</span></a>
                  <a href={`/api/findings/${f.id}/report?format=json`} download className="block rounded px-2.5 py-1.5 text-[12.5px] text-ink-800 hover:bg-ink-50">Evidence data (JSON)<span className="block text-[11px] text-ink-500">For case-management tools</span></a>
                </div>
              </details>
            </div>
          </div>
        </div>
        <div className="mt-4 rounded-md border border-ink-150 bg-ink-50 px-3.5 py-2.5">
          <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Why flagged?</div>
          <p className="mt-0.5 text-[13px] leading-relaxed text-ink-800">{f.explanation}</p>
        </div>
        <p className="mt-2 text-[11.5px] text-ink-400">
          Potential impersonation — review required. The score is heuristic triage evidence, not a probability and not proof of intent or ownership. Verify at the source before acting.
        </p>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px] [&>*]:min-w-0">
        <div className="min-w-0 space-y-4">
          {/* ------------------------------------------------ observed facts */}
          <Card>
            <CardHeader
              title="Observed facts"
              description={`Verbatim from the stored record collected ${pv ? dateTime(pv.collected_at) : ""} via ${synthetic ? "the bundled synthetic dataset" : sourceLabel(c.source)}. No interpretation.`}
            />
            <div className="px-4 py-3">
              {synthetic && <p className="mb-3 rounded-md border border-med/30 bg-med/5 px-3 py-2 text-[12px] text-ink-700">{pv?.source_type_note}</p>}
              <SectionLabel>Description as collected</SectionLabel>
              {c.description ? (
                <p className="mt-1.5 rounded-md border border-ink-150 bg-white px-3 py-2.5 text-[12.5px] leading-relaxed whitespace-pre-line text-ink-800">{c.description}</p>
              ) : (
                <p className="mt-1.5 text-[12.5px] text-ink-400">No description provided by the source.</p>
              )}
              {c.external_links.length > 0 && (
                <div className="mt-3">
                  <SectionLabel hint="shown as text, never fetched">Listed links</SectionLabel>
                  <ul className="mt-1.5 space-y-1">
                    {c.external_links.map((u) => (
                      <li key={u} className="flex items-center gap-2 text-[12px]">
                        <code className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink-800" title={u}>{u}</code>
                        {urlScores[u] !== undefined && <ScoreMeter value={urlScores[u]} />}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <dl className="mt-3 divide-y divide-ink-100 border-t border-ink-150 pt-1">
                {ev?.observed_facts.filter((x) => x.label !== "Description length" && x.label !== "Listed links").map((x) => (
                  <Row key={x.label} label={x.label} mono={/ID|URL/.test(x.label)}>{x.value}</Row>
                ))}
              </dl>
            </div>
          </Card>

          {/* ------------------------------------------------ inferences */}
          {ev && <InferenceGroups items={ev.inferences} notEvaluated={f.signals?.not_evaluated ?? []} />}

          {/* ------------------------------------------------ relationships */}
          {ev && <SharedIndicators id={id} ev={ev} />}

          {/* ------------------------------------------------ technical metadata */}
          <Card>
            <details>
              <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-[13px] font-medium text-ink-900">
                Technical metadata <span className="text-[11.5px] font-normal text-ink-500">raw source fields, provenance, hashes</span>
              </summary>
              <div className="space-y-3 border-t border-ink-150 px-4 py-3">
                <pre className="max-h-72 overflow-auto rounded-md bg-ink-50 p-3 font-mono text-[11px] leading-relaxed text-ink-700">{JSON.stringify({ external_id: c.external_id, source: c.source, metadata: c.metadata, provenance: c.provenance }, null, 2)}</pre>
                {sig.logo?.data && Object.keys(sig.logo.data).length > 0 && (
                  <pre className="overflow-auto rounded-md bg-ink-50 p-3 font-mono text-[11px] text-ink-700">{JSON.stringify({ logo_signal: sig.logo.data }, null, 2)}</pre>
                )}
                <p className="text-[11.5px] text-ink-500">Content hash of the latest observation: <code className="font-mono">{pv?.content_hash || "—"}</code></p>
              </div>
            </details>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          {/* ------------------------------------------------ comparison */}
          <Card>
            <CardHeader title="Compared with" description="Official assets from the brand profile" />
            <div className="flex items-center justify-around px-4 py-4">
              <figure className="text-center">
                {cmp?.logo.available ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`/api/brands/${f.brand_id}/logo`} alt="Brand logo" className="size-20 rounded-lg border border-ink-150 bg-white object-contain" />
                ) : (
                  <div className="grid size-20 place-items-center rounded-lg border border-dashed border-ink-200 text-[11px] text-ink-400">No logo</div>
                )}
                <figcaption className="mt-1.5 text-[11px] text-ink-500">Official logo</figcaption>
              </figure>
              <div className="text-center">
                <div className="tabular text-[18px] font-semibold text-ink-900">{sig.logo?.evaluated ? `${Math.round(sig.logo.score * 100)}%` : "—"}</div>
                <div className="text-[11px] text-ink-500">logo similarity</div>
              </div>
              <figure className="text-center">
                <Avatar url={c.avatar_url} name={c.name} size={80} square />
                <figcaption className="mt-1.5 text-[11px] text-ink-500">Candidate</figcaption>
              </figure>
            </div>
            {cmp && (
              <dl className="divide-y divide-ink-100 border-t border-ink-150 px-4 py-1">
                <Row label="Brand name">{cmp.matched_brand_name && cmp.matched_brand_name !== cmp.brand_name ? `${cmp.brand_name} (matched alias “${cmp.matched_brand_name}”)` : cmp.brand_name}</Row>
                {c.kind === "app" && (
                  <Row label="Official app">
                    {cmp.official_apps.length ? (
                      <ul className="space-y-1">
                        {cmp.official_apps.map((a) => (
                          <li key={a.store + a.app_id}>
                            <span className="text-ink-900">{a.name || a.app_id}</span> <span className="text-ink-500">· {sourceLabel(a.store)}{a.same_store ? "" : " (other store)"}</span>
                            <div className="font-mono text-[11px] text-ink-600">{a.app_id}</div>
                            <div className="text-[11.5px] text-ink-500">Developer {a.publisher_name || "—"}{a.publisher_id ? ` · ID ${a.publisher_id}` : ""}</div>
                          </li>
                        ))}
                      </ul>
                    ) : <span className="text-ink-400">None registered — publisher can’t be verified</span>}
                  </Row>
                )}
                {c.kind === "account" && (
                  <Row label="Official accounts">
                    {cmp.official_accounts.length ? cmp.official_accounts.map((a) => <div key={a.handle} className="font-mono text-[11.5px]">{a.handle}</div>) : <span className="text-ink-400">None on this platform</span>}
                  </Row>
                )}
                <Row label="Official domains">{cmp.official_domains.length ? cmp.official_domains.join(", ") : <span className="text-ink-400">None</span>}</Row>
                {sig.publisher?.evaluated && <Row label="Publisher check">{sig.publisher.detail}</Row>}
                {sig.description?.evaluated && <Row label="Description check">{sig.description.detail}</Row>}
              </dl>
            )}
            {cmp && <p className="border-t border-ink-150 px-4 py-2 text-[11px] text-ink-400">{cmp.note}</p>}
          </Card>

          {/* ------------------------------------------------ provenance */}
          <Card>
            <CardHeader title="Provenance" />
            <dl className="px-4 py-2">
              <Row label="Data type">{pv ? `${pv.source_type} — ${pv.source_type_note}` : c.source_type}</Row>
              <Row label="Collected via">{pv?.endpoint ?? "—"}</Row>
              <Row label="Matched queries">{pv?.queries.length ? pv.queries.map((q) => `“${q}”`).join(", ") : "—"}</Row>
              <Row label="First observed">{dateTime(c.first_observed_at)}</Row>
              <Row label="Last observed">{dateTime(c.last_observed_at)}</Row>
              <Row label="First seen in scan">{f.first_seen_scan_id ? <Link className="text-teal-700 hover:underline" href={`/app/scans/${f.first_seen_scan_id}`}>#{f.first_seen_scan_id}</Link> : "—"}</Row>
            </dl>
            {f.observations && f.observations.length > 0 && (
              <ul className="space-y-1 border-t border-ink-150 px-4 py-3">
                {f.observations.map((o) => (
                  <li key={o.scan_id} className="flex items-center justify-between text-[12px]">
                    <Link href={`/app/scans/${o.scan_id}`} className="text-ink-700 hover:underline">Scan #{o.scan_id} <span className="text-ink-400">· {o.trigger}</span></Link>
                    <span className="tabular text-ink-500" title={`content ${o.content_hash}`}>{o.risk_score?.toFixed(0)} · {relTime(o.observed_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* ------------------------------------------------ audit trail */}
          <Card>
            <CardHeader title="Review history" description="Every decision and note, with the status change it made" />
            {f.decisions && f.decisions.length ? (
              <ol className="space-y-3 px-4 py-3">
                {[...f.decisions].reverse().map((d) => (
                  <li key={d.id} className="text-[12.5px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-ink-900">{ACTION_LABEL[d.action] ?? d.action}</span>
                      <span className="text-[11.5px] text-ink-400" title={dateTime(d.created_at)}>{relTime(d.created_at)}</span>
                    </div>
                    <div className="text-[11.5px] text-ink-500">
                      {d.user}
                      {d.from_status && d.to_status && d.from_status !== d.to_status && <> · {STATUS_LABEL[d.from_status]} → {STATUS_LABEL[d.to_status]}</>}
                    </div>
                    {d.note && <p className="mt-1 rounded bg-ink-50 px-2 py-1.5 whitespace-pre-line text-ink-700">{d.note}</p>}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="px-4 py-3 text-[12.5px] text-ink-400">No analyst decisions yet.</p>
            )}
          </Card>
        </div>
      </div>

      <Dialog
        open={dialog !== null}
        onClose={() => setDialog(null)}
        title={dialog ? DIALOG[dialog].title : ""}
        description={dialog ? DIALOG[dialog].description : ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={() => dialog && decide(dialog, note)} disabled={dialog === "note" && !note.trim()}>
              {dialog === "note" ? "Add note" : "Save decision"}
            </Button>
          </>
        }
      >
        <Textarea aria-label="Note" placeholder={dialog ? DIALOG[dialog].placeholder : ""} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        <p className="mt-1.5 text-[11px] text-ink-400"><Kbd>Esc</Kbd> to cancel</p>
      </Dialog>
    </div>
  );
}

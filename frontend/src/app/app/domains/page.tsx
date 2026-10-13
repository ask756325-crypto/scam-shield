"use client";

import { ArrowUpRight, Download, Globe, Info, Radar, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChangeBadge, RiskBadge, StatusBadge } from "@/components/app/bits";
import { useBrands, useScans } from "@/components/app/providers";
import { SignalMeter } from "@/components/app/social-monitor";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Notice, PageHeader, Select, Skeleton, cx } from "@/components/ui";
import { api, buildQuery } from "@/lib/api";
import { dateTime, DETECTION_TYPE_LABELS, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Finding, Paged } from "@/lib/types";

const LEVELS = ["critical", "high", "medium", "low"] as const;
const SIGNALS = [{ key: "name", label: "Brand in name" }, { key: "urls", label: "URL risk" }, { key: "scam", label: "Scam wording" }];

function DomainRow({ f, onChange }: { f: Finding; onChange: (f: Finding) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const c = f.candidate;
  const m = c.metadata as { first_certificate_at?: string; issuers?: string[]; registrable_domain?: string };
  const decide = async (action: "confirm" | "mark_safe") => {
    setBusy(action);
    try {
      const u = await api<Finding>(`/findings/${f.id}/decision`, { method: "POST", body: { action, note: "" } });
      onChange({ ...f, status: u.status });
      toast({ tone: "success", title: action === "confirm" ? "Confirmed as impersonation" : "Marked legitimate" });
    } catch (e) {
      toast({ tone: "error", title: "Could not save decision", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  return (
    <article className="px-4 py-3.5" aria-labelledby={`dom-${f.id}`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-md border border-ink-150 bg-ink-50 text-ink-500"><Globe className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {/* Shown as text on purpose: a look-alike domain may be a live phishing site. */}
            <h3 id={`dom-${f.id}`} className="font-mono text-[13.5px] font-semibold break-all text-ink-950">{c.external_id}</h3>
            {f.detection_type && <Badge tone={f.detection_type === "phishing_domain" ? "crit" : "outline"}>{DETECTION_TYPE_LABELS[f.detection_type] ?? f.detection_type}</Badge>}
            <ChangeBadge state={f.change_state} />
          </div>
          <div className="mt-0.5 text-[12px] text-ink-500">
            First certificate {m.first_certificate_at ? dateTime(m.first_certificate_at) : "—"} · {(m.issuers ?? []).join(", ") || "unknown CA"}
            {m.registrable_domain && m.registrable_domain !== c.external_id && <> · registered domain <span className="font-mono">{m.registrable_domain}</span></>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <RiskBadge level={f.risk_level} score={f.risk_score} />
          <StatusBadge status={f.status} level={f.risk_level} />
        </div>
      </div>
      <div className="mt-2.5 grid max-w-md grid-cols-3 gap-x-4">
        {SIGNALS.map((s) => <SignalMeter key={s.key} label={s.label} s={f.signal_scores?.[s.key]} />)}
      </div>
      <p className="mt-2 text-[12.5px] text-ink-700"><span className="font-medium">{f.classification}.</span> {f.explanation}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {f.status !== "confirmed" && <Button size="sm" variant="primary" icon={<ShieldX className="size-3.5" />} loading={busy === "confirm"} disabled={!!busy} onClick={() => decide("confirm")}>Confirm</Button>}
        {f.status !== "safe" && <Button size="sm" icon={<ShieldCheck className="size-3.5" />} loading={busy === "mark_safe"} disabled={!!busy} onClick={() => decide("mark_safe")}>Mark legitimate</Button>}
        <Link href={`/app/investigations/${f.id}`} className="inline-flex h-7 items-center gap-1 px-1.5 text-[12.5px] font-medium text-teal-700 hover:underline">Investigate <ArrowUpRight className="size-3.5" /></Link>
        <span className="ml-auto text-[11.5px] text-ink-400">Seen {relTime(c.last_observed_at)}</span>
      </div>
    </article>
  );
}

export default function DomainsPage() {
  const { selected } = useBrands();
  const { active, startScan, version } = useScans();
  const [levels, setLevels] = useState<string[]>(["critical", "high", "medium"]);
  const [dtype, setDtype] = useState("");
  const [q, setQ] = useState("");
  const { data: cfg } = useApi<{ config: { enabled_sources: string[] } }>("/sources");
  const enabled = cfg?.config.enabled_sources.includes("ct_domains");
  const filters = useMemo(() => ({ brand_id: selected?.id, kind: "domain", level: levels.length ? levels : [...LEVELS], detection_type: dtype ? [dtype] : undefined, q: q || undefined }), [selected?.id, levels, dtype, q]);
  const { data, error, loading, reload, setData } = useApi<Paged<Finding>>(selected ? "/findings" : null, { ...filters, include_signals: true, sort: "risk", limit: 100 });
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);
  if (!selected) return null;
  const running = active.find((s) => s.brand_id === selected.id);

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        eyebrow="Monitor"
        title="Domain Monitoring"
        description={`Newly certified web domains containing ${selected.name}’s name, found in public Certificate Transparency logs. Official domains (and subdomains you control) are excluded. Domains are analysed as text only — never visited.`}
        actions={enabled && !selected.is_demo ? (
          <Button variant="primary" icon={<Radar className="size-3.5" />} loading={!!running} disabled={!!running} onClick={() => startScan(selected.id, ["ct_domains"])}>Scan domains</Button>
        ) : undefined}
      />
      {selected.is_demo && <Notice tone="warn" icon={<Info className="size-4" />}>The synthetic demo dataset has no domains. Create a real brand to search Certificate Transparency logs.</Notice>}
      {!selected.is_demo && cfg && !enabled && (
        <Notice tone="teal">Domain monitoring is off. <Link href="/app/sources" className="font-medium underline">Enable “Look-alike domains (CT logs)”</Link> on Sources & Integrations — it is opt-in because crt.sh is a free, sometimes slow community service.</Notice>
      )}
      <Card className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-150 px-3 py-2.5">
          <Input aria-label="Search domains" placeholder="Domain…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 w-full sm:w-56" />
          <div role="group" aria-label="Risk level" className="flex gap-1">
            {LEVELS.map((l) => {
              const on = levels.includes(l);
              return (
                <button key={l} aria-pressed={on} onClick={() => setLevels((ls) => (on ? ls.filter((x) => x !== l) : [...ls, l]))}
                  className={cx("h-8 rounded-md border px-2.5 text-[12px] font-medium capitalize", on ? "border-ink-800 bg-ink-800 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300")}>{l}</button>
              );
            })}
          </div>
          <Select aria-label="Detection type" value={dtype} onChange={(e) => setDtype(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">All types</option>
            <option value="phishing_domain">Possible phishing domain</option>
            <option value="lookalike_domain">Look-alike domain</option>
          </Select>
          <a href={`/api/findings/export.csv${buildQuery(filters)}`} download className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-md border border-ink-200 bg-white px-2.5 text-[12.5px] font-medium text-ink-700 hover:border-ink-300">
            <Download className="size-3.5" /> Export CSV
          </a>
        </div>
        {error && <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div>}
        {loading && !data ? <div className="space-y-3 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
          : data && data.items.length === 0 ? (
            <EmptyState icon={<Globe className="size-5" />} title="No look-alike domains" description={enabled ? "No matching domains at these levels. Include “low” or run a domain scan." : "Enable domain monitoring to start."} />
          ) : (
            <div className="divide-y divide-ink-150">
              {data?.items.map((f) => <DomainRow key={f.id} f={f} onChange={(nf) => setData({ ...data, items: data.items.map((x) => (x.id === nf.id ? nf : x)) })} />)}
            </div>
          )}
      </Card>
    </div>
  );
}

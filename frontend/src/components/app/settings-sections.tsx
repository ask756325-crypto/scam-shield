"use client";

import { CalendarClock, Download, LogOut, MonitorSmartphone, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Schedule, SchedulerStatus } from "@/lib/types";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, Dialog, ErrorState, Field, Input, Notice, Select, Skeleton } from "../ui";
import { StatusDot } from "./bits";

// ---------------------------------------------------------------- sessions

interface SessionRow { id: number; created_at: string; expires_at: string; user_agent: string | null; current: boolean }

function deviceLabel(ua: string | null) {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : /python|httpx|curl/i.test(ua) ? "API client" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

export function SessionsCard() {
  const toast = useToast();
  const { data, error, reload } = useApi<SessionRow[]>("/auth/sessions");
  const [busy, setBusy] = useState<string | null>(null);
  const others = (data ?? []).filter((s) => !s.current);

  const revoke = async (id?: number) => {
    setBusy(id ? String(id) : "all");
    try {
      if (id) await api(`/auth/sessions/${id}`, { method: "DELETE" });
      else await api("/auth/logout-others", { method: "POST" });
      toast({ tone: "success", title: id ? "Session signed out" : "Signed out of all other sessions" });
      reload(true);
    } catch (e) {
      toast({ tone: "error", title: "Could not sign out", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Active sessions"
        description="Where your account is signed in. Signing a session out revokes it on the server immediately."
        actions={others.length > 0 && <Button size="sm" icon={<LogOut className="size-3.5" />} loading={busy === "all"} onClick={() => revoke()}>Sign out other sessions</Button>}
      />
      {error ? <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div> : !data ? <div className="p-4"><Skeleton className="h-12" /></div> : (
        <ul className="divide-y divide-ink-150">
          {data.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[12.5px]">
              <MonitorSmartphone className="size-4 text-ink-400" />
              <div className="min-w-0 flex-1">
                <div className="font-medium text-ink-900">{deviceLabel(s.user_agent)} {s.current && <Badge tone="forest">This session</Badge>}</div>
                <div className="text-[11.5px] text-ink-500">Signed in {relTime(s.created_at)} · expires {dateTime(s.expires_at)}</div>
              </div>
              {!s.current && <Button size="sm" variant="ghost" loading={busy === String(s.id)} onClick={() => revoke(s.id)}>Sign out</Button>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- monitoring

interface MonitoringResp {
  values: { resolve_after_misses: number; max_queries_per_source: number; source_time_budget_seconds: number; max_image_fetches: number; scan_history_days: number | null };
  defaults: MonitoringResp["values"];
  limits: Record<string, { min: number; max: number; description: string }>;
  retention_choices: (number | null)[];
}
type LimitKey = "resolve_after_misses" | "max_queries_per_source" | "source_time_budget_seconds" | "max_image_fetches";
const LIMIT_LABEL: Record<LimitKey, string> = {
  max_queries_per_source: "Queries per source per scan",
  source_time_budget_seconds: "Time budget per source (seconds)",
  max_image_fetches: "Logo images fetched per scan",
  resolve_after_misses: "Resolve after consecutive clean misses",
};

export function MonitoringTab({ owner }: { owner: boolean }) {
  const toast = useToast();
  const { data, error, setData } = useApi<MonitoringResp>("/settings/monitoring");
  const { data: sched } = useApi<{ scheduler: SchedulerStatus; items: Schedule[] }>("/schedules");
  const { data: src } = useApi<{ config: { enabled_sources: string[] } }>("/sources");
  const [draft, setDraft] = useState<Record<LimitKey, string> | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setDraft(Object.fromEntries((Object.keys(LIMIT_LABEL) as LimitKey[]).map((k) => [k, String(data.values[k])])) as Record<LimitKey, string>);
  }, [data]);
  if (error) return <ErrorState error={error} />;
  if (!data || !draft) return <Skeleton className="h-64" />;

  // Inline validation against the server's published ranges.
  const local: Record<string, string> = {};
  for (const k of Object.keys(LIMIT_LABEL) as LimitKey[]) {
    const v = Number(draft[k]);
    const { min, max } = data.limits[k];
    if (draft[k] === "" || !Number.isInteger(v) || v < min || v > max) local[k] = `Whole number from ${min} to ${max}`;
  }
  const dirty = (Object.keys(LIMIT_LABEL) as LimitKey[]).some((k) => String(data.values[k]) !== draft[k]);

  const save = async () => {
    setBusy(true);
    setErrors({});
    try {
      const body = Object.fromEntries((Object.keys(LIMIT_LABEL) as LimitKey[]).map((k) => [k, Number(draft[k])]));
      setData(await api<MonitoringResp>("/settings/monitoring", { method: "PUT", body }));
      toast({ tone: "success", title: "Monitoring settings saved", description: "Applies from the next scan." });
    } catch (e) {
      const d = e instanceof ApiError ? (e.data as { detail?: { errors?: Record<string, string> } })?.detail : undefined;
      if (d?.errors) setErrors(d.errors);
      toast({ tone: "error", title: "Not saved", description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><CalendarClock className="size-4 text-ink-500" /> Scan schedules</span>}
          description="Each brand has its own schedule (interval, time zone, sources) on its Monitoring tab."
        />
        {sched && !sched.scheduler.healthy && <div className="px-4 pt-3"><Notice tone="warn">{sched.scheduler.message}</Notice></div>}
        {!sched ? <div className="p-4"><Skeleton className="h-10" /></div> : sched.items.length === 0 ? (
          <p className="px-4 py-3 text-[12.5px] text-ink-500">No schedules yet — scans run only when started manually. Open a brand’s <span className="font-medium">Monitoring</span> tab to add one.</p>
        ) : (
          <ul className="divide-y divide-ink-150">
            {sched.items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[12.5px]">
                <StatusDot status={s.state === "active" ? "ok" : s.state === "paused" ? "partial" : "skipped"} />
                <Link href={`/app/brands/${s.brand_id}?tab=monitoring`} className="font-medium text-teal-700 hover:underline">{s.brand_name}</Link>
                <span className="text-ink-600">{s.state === "active" ? s.description : s.state === "paused" ? "Paused" : "Disabled"}</span>
                {s.state === "active" && s.next_run_at && <span className="text-ink-500">· next {relTime(s.next_run_at)}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Enabled sources"
          description="Which integrations scans use, their health and configuration."
          actions={<Link href="/app/sources" className="text-[12px] font-medium text-teal-700 hover:underline">Manage sources</Link>}
        />
        <p className="px-4 py-3 text-[12.5px] text-ink-700">{src ? (src.config.enabled_sources.length ? src.config.enabled_sources.map(sourceLabel).join(", ") : "No sources enabled") : "…"}</p>
      </Card>

      <Card>
        <CardHeader title="Source limits and resolution rule" description={owner ? "Keep requests well inside each source’s documented limits. Applies to every brand." : "Only organization owners can change these settings."} />
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          {(Object.keys(LIMIT_LABEL) as LimitKey[]).map((k) => (
            <Field key={k} label={LIMIT_LABEL[k]} htmlFor={`mon-${k}`} hint={`${data.limits[k].description}. Default ${data.defaults[k]}.`} error={errors[k] ?? (draft[k] !== String(data.values[k]) ? local[k] : null)}>
              <Input id={`mon-${k}`} type="number" inputMode="numeric" min={data.limits[k].min} max={data.limits[k].max} className="w-32" disabled={!owner}
                value={draft[k]} aria-invalid={!!(errors[k] || local[k])} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
            </Field>
          ))}
        </div>
        <div className="flex justify-end gap-2 border-t border-ink-150 px-4 py-3">
          {dirty && <Button variant="ghost" onClick={() => setData({ ...data })}>Discard</Button>}
          <Button variant="primary" disabled={!owner || !dirty || Object.keys(local).length > 0} loading={busy} onClick={save}>Save monitoring settings</Button>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- data management

interface DataResp {
  counts: { brands: number; findings: number; decisions: number; scans: number; connectivity_tests: number };
  retention: { days: number | null; scans: number; observations: number; changes: number; exclusions: number };
}

export function DataTab({ owner }: { owner: boolean }) {
  const toast = useToast();
  const { data, error, reload } = useApi<DataResp>("/settings/data");
  const { data: mon, setData: setMon } = useApi<MonitoringResp>("/settings/monitoring");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorState error={error} />;
  if (!data || !mon) return <Skeleton className="h-64" />;
  const days = mon.values.scan_history_days;

  const setRetention = async (v: number | null) => {
    try {
      setMon(await api<MonitoringResp>("/settings/monitoring", { method: "PUT", body: { scan_history_days: v } }));
      toast({ tone: "success", title: v ? `Scan history kept for ${v} days` : "Scan history kept forever" });
      reload(true);
    } catch (e) {
      toast({ tone: "error", title: "Not saved", description: (e as Error).message });
    }
  };
  const purge = async () => {
    setBusy(true);
    try {
      const r = await api<{ deleted: DataResp["retention"] }>("/settings/data/purge", { method: "POST", body: { confirm: typed } });
      toast({ tone: "success", title: `Deleted ${r.deleted.scans} old scan${r.deleted.scans === 1 ? "" : "s"}`, description: "Findings and the review audit trail were kept." });
      setConfirmOpen(false);
      setTyped("");
      reload(true);
    } catch (e) {
      toast({ tone: "error", title: "Nothing deleted", description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const exports = [
    { href: "/api/findings/export.csv", label: "Findings", hint: "All findings with risk, status, evidence summary and provenance" },
    { href: "/api/scans/export.csv", label: "Scan history", hint: "Every scan with per-source failures and change counts" },
    { href: "/api/settings/data/decisions.csv", label: "Review audit trail", hint: "Every decision and note, with analyst and status change" },
  ];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Your organization’s data" description="Everything below is scoped to this organization; other organizations’ data is never included." />
        <dl className="grid grid-cols-2 gap-y-3 px-4 py-3 sm:grid-cols-5">
          {Object.entries(data.counts).map(([k, v]) => (
            <div key={k}><dt className="text-[11.5px] text-ink-500 capitalize">{k.replace("_", " ")}</dt><dd className="tabular text-[18px] font-semibold text-ink-950">{v}</dd></div>
          ))}
        </dl>
      </Card>

      <Card>
        <CardHeader title="Export (CSV)" description="Spreadsheet-safe: cells that could run as formulas are neutralised." />
        <ul className="divide-y divide-ink-150">
          {exports.map((x) => (
            <li key={x.href} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1"><div className="text-[12.5px] font-medium text-ink-900">{x.label}</div><div className="text-[11.5px] text-ink-500">{x.hint}</div></div>
              <a href={x.href} download className="inline-flex h-8 items-center gap-1.5 rounded-md border border-ink-200 bg-white px-2.5 text-[12.5px] font-medium text-ink-700 hover:border-ink-300">
                <Download className="size-3.5" /> Download
              </a>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader
          title="Retention"
          description="Old scan history (per-scan source results, observations, change records and exclusion log) can be removed automatically. Findings, their latest evidence and the review audit trail are always kept, as is each brand’s most recent scan."
        />
        <div className="flex flex-wrap items-end gap-4 p-4">
          <Field label="Keep scan history for" htmlFor="ret">
            <Select id="ret" className="w-48" disabled={!owner} value={days ?? ""} onChange={(e) => setRetention(e.target.value === "" ? null : Number(e.target.value))}>
              {mon.retention_choices.map((c) => <option key={String(c)} value={c ?? ""}>{c ? `${c} days` : "Forever (default)"}</option>)}
            </Select>
          </Field>
          {days ? (
            <p className="pb-1.5 text-[12px] text-ink-600">
              Applied automatically once a day by the scheduler. Right now {data.retention.scans} scan{data.retention.scans === 1 ? "" : "s"} ({data.retention.observations} observations) {data.retention.scans === 1 ? "is" : "are"} older than {days} days.
            </p>
          ) : (
            <p className="pb-1.5 text-[12px] text-ink-500">Nothing is deleted automatically.</p>
          )}
          {owner && days && data.retention.scans > 0 && (
            <Button variant="danger" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmOpen(true)}>Delete now…</Button>
          )}
        </div>
        {!owner && <p className="border-t border-ink-150 px-4 py-2 text-[11.5px] text-ink-500">Only organization owners can change retention or delete data.</p>}
      </Card>

      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Delete old scan history?"
        description={`This permanently deletes ${data.retention.scans} scan(s) older than ${days} days, with ${data.retention.observations} observation(s), ${data.retention.changes} change record(s) and ${data.retention.exclusions} exclusion log row(s). Findings and decisions are kept. This cannot be undone.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button variant="danger" loading={busy} disabled={typed !== "DELETE"} onClick={purge}>Delete scan history</Button>
          </>
        }
      >
        <Field label={<>Type <code className="font-mono">DELETE</code> to confirm</>} htmlFor="purge-confirm">
          <Input id="purge-confirm" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
        </Field>
      </Dialog>
    </div>
  );
}

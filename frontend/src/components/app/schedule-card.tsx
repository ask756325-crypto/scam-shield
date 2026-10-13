"use client";

import { AlertTriangle, CalendarClock, Pause, Play, Power, Settings2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Brand, Frequency, Schedule, SchedulerStatus } from "@/lib/types";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, Checkbox, Field, Input, Notice, Segmented, Select, Skeleton, cx } from "../ui";
import { useBrands } from "./providers";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const INTERVALS = [1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 168];
const OUTCOME: Record<string, { label: string; tone: "forest" | "med" | "crit" | "outline" | "teal" }> = {
  started: { label: "Running", tone: "teal" },
  completed: { label: "Completed", tone: "forest" },
  partial: { label: "Partial", tone: "med" },
  failed: { label: "Failed", tone: "crit" },
  skipped_overlap: { label: "Skipped — scan already running", tone: "outline" },
  deferred: { label: "Deferred — scheduler busy", tone: "outline" },
  error: { label: "Could not start", tone: "crit" },
};

function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function zones(): string[] {
  try {
    const z = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone");
    if (z?.length) return z.includes("UTC") ? z : ["UTC", ...z];
  } catch {
    /* older browsers */
  }
  return ["UTC", browserTz()];
}

/** "Mon 13 Oct, 09:00" in the given zone. */
function inZone(iso: string, tz: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: tz }).format(new Date(iso));
}

interface Draft { frequency: Frequency; interval_hours: number; time_of_day: string; weekdays: number[]; timezone: string; sources: string[] | null }

function Editor({ brand, initial, enabledSources, onSaved, onCancel }: { brand: Brand; initial: Draft; enabledSources: string[]; onSaved: (s: Schedule) => void; onCancel?: () => void }) {
  const toast = useToast();
  const [d, setD] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [fieldErr, setFieldErr] = useState<{ field?: string; message?: string }>({});
  const allZones = useMemo(zones, []);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const chosen = d.sources ?? enabledSources;

  const save = async () => {
    setBusy(true);
    setFieldErr({});
    try {
      const s = await api<Schedule>(`/brands/${brand.id}/schedule`, { method: "PUT", body: { ...d, sources: d.sources && d.sources.length < enabledSources.length ? d.sources : null } });
      toast({ tone: "success", title: "Schedule saved", description: s.next_run_local ? `Next scan ${inZone(s.next_run_at!, s.timezone)} (${s.timezone})` : undefined });
      onSaved(s);
    } catch (e) {
      const detail = e instanceof ApiError ? ((e.data as { detail?: { field?: string; message?: string } })?.detail ?? {}) : {};
      setFieldErr(typeof detail === "object" ? detail : {});
      toast({ tone: "error", title: "Could not save schedule", description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 p-4">
      <Segmented<Frequency>
        label="Frequency"
        value={d.frequency}
        onChange={(v) => set("frequency", v)}
        options={[{ value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" }, { value: "interval", label: "Every N hours" }]}
      />
      <div className="flex flex-wrap gap-4">
        {d.frequency === "interval" ? (
          <Field label="Interval" htmlFor="sch-interval" error={fieldErr.field === "interval_hours" ? fieldErr.message : null}>
            <Select id="sch-interval" value={d.interval_hours} onChange={(e) => set("interval_hours", Number(e.target.value))} className="w-44">
              {INTERVALS.map((h) => <option key={h} value={h}>{h < 24 ? `Every ${h} hour${h > 1 ? "s" : ""}` : h === 168 ? "Every 7 days" : `Every ${h / 24} day${h > 24 ? "s" : ""}`}</option>)}
            </Select>
          </Field>
        ) : (
          <Field label="Local time" htmlFor="sch-time" error={fieldErr.field === "time_of_day" ? fieldErr.message : null}>
            <Input id="sch-time" type="time" value={d.time_of_day} onChange={(e) => set("time_of_day", e.target.value)} className="w-32" />
          </Field>
        )}
        <Field label="Time zone" htmlFor="sch-tz" hint={d.frequency === "interval" ? "Used to display run times" : "Runs at this local time, including across daylight-saving changes"} error={fieldErr.field === "timezone" ? fieldErr.message : null}>
          <Select id="sch-tz" value={d.timezone} onChange={(e) => set("timezone", e.target.value)} className="w-64">
            {allZones.map((z) => <option key={z} value={z}>{z}</option>)}
          </Select>
        </Field>
      </div>
      {d.frequency === "weekly" && (
        <Field label="Days" error={fieldErr.field === "weekdays" ? fieldErr.message : null}>
          <div role="group" aria-label="Days of the week" className="flex flex-wrap gap-1">
            {DAYS.map((name, i) => {
              const on = d.weekdays.includes(i);
              return (
                <button key={name} type="button" aria-pressed={on} onClick={() => set("weekdays", on ? d.weekdays.filter((x) => x !== i) : [...d.weekdays, i].sort())}
                  className={cx("h-8 w-11 rounded-md border text-[12px] font-medium", on ? "border-ink-800 bg-ink-800 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300")}>
                  {name}
                </button>
              );
            })}
          </div>
        </Field>
      )}
      {enabledSources.length > 1 && (
        <Field label="Sources" hint="Unselected sources are not queried by scheduled scans." error={fieldErr.field === "sources" ? fieldErr.message : null}>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {enabledSources.map((src) => (
              <Checkbox key={src} label={sourceLabel(src)} checked={chosen.includes(src)}
                onChange={(v) => set("sources", v ? [...chosen, src] : chosen.filter((x) => x !== src))} />
            ))}
          </div>
        </Field>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" loading={busy} disabled={chosen.length === 0 || (d.frequency === "weekly" && d.weekdays.length === 0)} onClick={save}>Save schedule</Button>
        {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
        <span className="text-[11.5px] text-ink-500">Saving activates the schedule and plans the next run from now.</span>
      </div>
    </div>
  );
}

export function ScheduleCard({ brand }: { brand: Brand }) {
  const toast = useToast();
  const { reloadBrands } = useBrands();
  const { data, loading, setData, reload } = useApi<{ configured: boolean; schedule: Schedule | null }>(`/brands/${brand.id}/schedule`);
  const { data: status } = useApi<SchedulerStatus>("/scheduler/status");
  const { data: cfg } = useApi<{ config: { enabled_sources: string[] } }>("/sources");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const viewerTz = useMemo(browserTz, []);
  useEffect(() => setEditing(false), [brand.id]);

  const s = data?.schedule ?? null;
  const enabledSources = brand.is_demo ? ["demo"] : cfg?.config.enabled_sources ?? [];

  const act = async (action: "pause" | "resume" | "disable") => {
    setBusy(action);
    try {
      const out = await api<Schedule>(`/brands/${brand.id}/schedule/${action}`, { method: "POST" });
      setData({ configured: true, schedule: out });
      reloadBrands();
      toast({ tone: "success", title: { pause: "Schedule paused", resume: "Schedule resumed", disable: "Schedule disabled" }[action] });
    } catch (e) {
      toast({ tone: "error", title: "Could not update schedule", description: (e as Error).message });
      reload(true);
    } finally {
      setBusy(null);
    }
  };
  const saved = (out: Schedule) => {
    setData({ configured: true, schedule: out });
    setEditing(false);
    reloadBrands();
  };

  const draft: Draft = s
    ? { frequency: s.frequency, interval_hours: s.interval_hours, time_of_day: s.time_of_day, weekdays: s.weekdays, timezone: s.timezone, sources: s.sources }
    : { frequency: "daily", interval_hours: 24, time_of_day: "09:00", weekdays: [0], timezone: viewerTz, sources: null };
  const outcome = s?.last_outcome ? OUTCOME[s.last_outcome] ?? { label: s.last_outcome, tone: "outline" as const } : null;

  return (
    <Card>
      <CardHeader
        title={<span className="inline-flex items-center gap-2"><CalendarClock className="size-4 text-ink-500" /> Monitoring schedule</span>}
        description="Recurring scans run on the server — no browser needs to stay open. Each scan is compared with earlier ones to flag new, changed, missing and resolved findings."
        actions={s && !editing && (
          <div className="flex flex-wrap gap-1.5">
            {s.state === "active" && <Button size="sm" icon={<Pause className="size-3.5" />} loading={busy === "pause"} disabled={!!busy} onClick={() => act("pause")}>Pause</Button>}
            {s.state !== "active" && <Button size="sm" variant="primary" icon={<Play className="size-3.5" />} loading={busy === "resume"} disabled={!!busy} onClick={() => act("resume")}>Resume</Button>}
            {s.state !== "disabled" && <Button size="sm" variant="ghost" icon={<Power className="size-3.5" />} loading={busy === "disable"} disabled={!!busy} onClick={() => act("disable")}>Disable</Button>}
            <Button size="sm" variant="ghost" icon={<Settings2 className="size-3.5" />} onClick={() => setEditing(true)}>Edit</Button>
          </div>
        )}
      />
      {status && !status.healthy && (
        <div className="px-4 pt-3">
          <Notice tone="warn" icon={<AlertTriangle className="size-4" />}>
            <strong className="font-medium">Scheduler not running.</strong> {status.message} Scheduled scans will not start until it is.
          </Notice>
        </div>
      )}
      {loading && !data ? (
        <div className="p-4"><Skeleton className="h-20" /></div>
      ) : !s ? (
        <>
          <p className="px-4 pt-3 text-[12.5px] text-ink-600">No schedule yet — {brand.name} is scanned only when someone presses “Scan now”.</p>
          <Editor brand={brand} initial={draft} enabledSources={enabledSources} onSaved={saved} />
        </>
      ) : editing ? (
        <Editor brand={brand} initial={draft} enabledSources={enabledSources} onSaved={saved} onCancel={() => setEditing(false)} />
      ) : (
        <div className="grid gap-4 p-4 md:grid-cols-[1fr_1fr]">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={s.state === "active" ? "forest" : s.state === "paused" ? "med" : "outline"} dot>{s.state === "active" ? "Active" : s.state === "paused" ? "Paused" : "Disabled"}</Badge>
              <span className="text-[13px] font-medium text-ink-900">{s.description}</span>
            </div>
            <div className="mt-1 text-[12px] text-ink-500">Sources: {(s.sources ?? enabledSources).map(sourceLabel).join(", ") || "—"}</div>
            {s.paused_reason && s.state !== "active" && <p className="mt-2 text-[12px] text-ink-600">{s.paused_reason}</p>}
            {s.state === "active" && s.next_run_at && (
              <div className="mt-3">
                <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Next runs</div>
                <ul className="mt-1 space-y-0.5 text-[12.5px]">
                  {s.upcoming.map((u, i) => (
                    <li key={u.utc} className={cx("tabular", i === 0 ? "font-medium text-ink-900" : "text-ink-600")}>
                      {inZone(u.utc, s.timezone)} <span className="text-ink-400">{s.timezone}</span>
                      {viewerTz !== s.timezone && <span className="text-ink-400"> · {inZone(u.utc, viewerTz)} your time</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="rounded-md border border-ink-150 bg-ink-50/60 px-3 py-2.5 text-[12.5px]">
            <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Last scheduled run</div>
            {s.last_run_at ? (
              <>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {outcome && <Badge tone={outcome.tone}>{outcome.label}</Badge>}
                  <span className="text-ink-600" title={dateTime(s.last_run_at)}>{relTime(s.last_run_at)}</span>
                  {s.last_scan_id && <Link href={`/app/scans/${s.last_scan_id}`} className="text-teal-700 hover:underline">Scan #{s.last_scan_id}</Link>}
                </div>
                {s.last_error && <p className="mt-1 text-[12px] text-ink-600">{s.last_error}</p>}
                {s.consecutive_failures > 0 && <p className="mt-1 text-[12px] text-crit">{s.consecutive_failures} consecutive failure{s.consecutive_failures > 1 ? "s" : ""} — retries back off; the schedule pauses itself after 5.</p>}
              </>
            ) : outcome ? (
              <div className="mt-1 flex flex-wrap items-center gap-2"><Badge tone={outcome.tone}>{outcome.label}</Badge><span className="text-ink-600">{s.last_error}</span></div>
            ) : (
              <p className="mt-1 text-ink-500">Not run yet.</p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

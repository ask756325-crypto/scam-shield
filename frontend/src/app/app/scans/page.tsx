"use client";

import { AlertTriangle, CalendarClock, ChevronLeft, ChevronRight, History } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { StatusDot } from "@/components/app/bits";
import { useBrands, useScans } from "@/components/app/providers";
import { Badge, Button, Card, EmptyState, ErrorState, Notice, PageHeader, ProgressBar, Segmented, Select, Skeleton, cx } from "@/components/ui";
import { apiPage } from "@/lib/api";
import { dateTime, duration, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Scan, Schedule, SchedulerStatus } from "@/lib/types";

const PAGE = 25;
const RANGES: Record<string, number | null> = { any: null, "24h": 1, "7d": 7, "30d": 30 };

function SchedulesStrip({ brandId }: { brandId?: number }) {
  const { data } = useApi<{ scheduler: SchedulerStatus; items: Schedule[] }>("/schedules");
  if (!data) return null;
  const items = brandId ? data.items.filter((s) => s.brand_id === brandId) : data.items;
  const st = data.scheduler;
  return (
    <Card className="mb-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-[12.5px]">
        <span className="inline-flex items-center gap-1.5 font-medium text-ink-900"><CalendarClock className="size-4 text-ink-500" /> Scheduled monitoring</span>
        <span className={cx("inline-flex items-center gap-1.5", st.healthy ? "text-forest-700" : "text-med")}>
          <span className={cx("size-1.5 rounded-full", st.healthy ? "bg-forest-600" : "bg-med")} />
          {st.healthy ? `Scheduler running (${st.runner}) · last check ${relTime(st.last_tick_at)}` : "Scheduler not running"}
        </span>
        {items.length === 0 ? (
          <span className="text-ink-500">No schedules{brandId ? " for this brand" : ""} — scans run only when started manually.</span>
        ) : (
          items.map((s) => (
            <Link key={s.id} href={`/app/brands/${s.brand_id}?tab=monitoring`} className="inline-flex items-center gap-1.5 rounded-md border border-ink-150 bg-white px-2 py-1 text-[12px] hover:border-ink-300">
              <StatusDot status={s.state === "active" ? "ok" : s.state === "paused" ? "partial" : "skipped"} />
              {!brandId && <span className="font-medium text-ink-900">{s.brand_name}</span>}
              <span className="text-ink-600">{s.state === "active" ? s.description : s.state === "paused" ? "Paused" : "Disabled"}</span>
              {s.state === "active" && s.next_run_at && <span className="text-ink-400">· next {relTime(s.next_run_at)}</span>}
              {s.consecutive_failures > 0 && <span className="text-crit">· {s.consecutive_failures} failed</span>}
            </Link>
          ))
        )}
      </div>
      {!st.healthy && st.message && (
        <div className="border-t border-ink-150 px-4 py-2.5"><Notice tone="warn" icon={<AlertTriangle className="size-4" />}>{st.message}</Notice></div>
      )}
    </Card>
  );
}

export default function ScansPage() {
  const { selected } = useBrands();
  const { version, active } = useScans();
  const router = useRouter();
  const [scope, setScope] = useState<"brand" | "all">("brand");
  const [trigger, setTrigger] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [failures, setFailures] = useState("");
  const [range, setRange] = useState("any");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<Scan[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const brandId = scope === "brand" ? selected?.id : undefined;
  useEffect(() => setPage(0), [brandId, trigger, status, source, failures, range]);

  const load = useCallback(async () => {
    const days = RANGES[range];
    try {
      const r = await apiPage<Scan[]>("/scans", {
        query: {
          brand_id: brandId, trigger: trigger || undefined, status: status ? status.split(",") : undefined, source: source || undefined,
          has_failures: failures || undefined, since: days ? new Date(Date.now() - days * 86400_000).toISOString() : undefined,
          limit: PAGE, offset: page * PAGE,
        },
      });
      setData(r.data);
      setTotal(r.total);
      setError(null);
    } catch (e) {
      setError(e as Error);
    }
  }, [brandId, trigger, status, source, failures, range, page]);
  useEffect(() => {
    load();
  }, [load, version]);
  useEffect(() => {
    if (!active.length) return;
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, [active.length, load]);

  const pages = Math.max(1, Math.ceil(total / PAGE));
  const filtered = !!(trigger || status || source || failures || range !== "any");

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Investigate"
        title="Scan History"
        description="Every manual, scheduled and import scan with real per-source outcomes. Findings are resolved only after consecutive clean scans miss them; failed or incomplete sources never resolve anything."
        actions={<Segmented label="Scope" value={scope} onChange={setScope} options={[{ value: "brand", label: selected ? selected.name : "This brand" }, { value: "all", label: "All brands" }]} />}
      />
      <SchedulesStrip brandId={brandId} />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-150 px-3 py-2.5">
          <Select aria-label="Trigger" value={trigger} onChange={(e) => setTrigger(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">All triggers</option>
            <option value="manual">Manual</option>
            <option value="scheduled">Scheduled</option>
            <option value="import">Import</option>
          </Select>
          <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">Any status</option>
            <option value="completed">Completed</option>
            <option value="partial">Partial</option>
            <option value="failed">Failed</option>
            <option value="queued,running">In progress</option>
          </Select>
          <Select aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">Any source</option>
            {["bluesky", "mastodon", "apple_app_store", "google_play", "demo", "import"].map((s) => <option key={s} value={s}>{sourceLabel(s)}</option>)}
          </Select>
          <Select aria-label="Source failures" value={failures} onChange={(e) => setFailures(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="">With or without failures</option>
            <option value="true">Any source failed</option>
            <option value="false">No source failures</option>
          </Select>
          <Select aria-label="Date range" value={range} onChange={(e) => setRange(e.target.value)} className="h-8 w-auto text-[12.5px]">
            <option value="any">All time</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </Select>
          {filtered && <Button size="sm" variant="ghost" onClick={() => { setTrigger(""); setStatus(""); setSource(""); setFailures(""); setRange("any"); }}>Clear filters</Button>}
          <span className="tabular ml-auto text-[12px] text-ink-500">{total} scan{total === 1 ? "" : "s"}</span>
        </div>
        {error && <div className="p-3"><ErrorState error={error} onRetry={load} /></div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-[12.5px]">
            <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
              <tr>
                <th className="py-2 pr-3 pl-4 font-medium">Scan</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Sources</th>
                <th className="px-3 py-2 text-right font-medium">Candidates</th>
                <th className="px-3 py-2 text-right font-medium">Official excl.</th>
                <th className="px-3 py-2 font-medium">Findings</th>
                <th className="py-2 pr-4 pl-3 font-medium">Started · duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-150">
              {!data
                ? Array.from({ length: 5 }).map((_, i) => <tr key={i}><td colSpan={7} className="px-4 py-3"><Skeleton className="h-6" /></td></tr>)
                : data.map((s) => (
                    <tr key={s.id} className="cursor-pointer hover:bg-white" onClick={() => router.push(`/app/scans/${s.id}`)}>
                      <td className="py-2.5 pr-3 pl-4">
                        <Link href={`/app/scans/${s.id}`} onClick={(e) => e.stopPropagation()} className="font-medium text-ink-900 hover:underline">#{s.id}</Link>
                        {scope === "all" && <span className="text-ink-500"> · {s.brand_name}</span>}
                        <div className="mt-0.5 flex gap-1">
                          <Badge tone={s.trigger === "scheduled" ? "teal" : "outline"} className="capitalize">{s.trigger === "scheduled" && <CalendarClock className="size-3" />}{s.trigger}</Badge>
                          {s.mode === "demo" && <Badge tone="med">Synthetic</Badge>}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        {s.status === "running" || s.status === "queued" ? (
                          <div className="w-32">
                            <div className="mb-1 flex items-center gap-1.5 text-teal-700"><StatusDot status="running" /> {Math.round(s.progress * 100)}%</div>
                            <ProgressBar value={s.progress} />
                          </div>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-ink-800 capitalize"><StatusDot status={s.status} /> {s.status}</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-x-2.5 gap-y-1">
                          {s.sources.map((x) => (
                            <span key={x.source} className={cx("inline-flex items-center gap-1 text-[11.5px]", x.status === "failed" || x.status === "partial" ? "text-ink-800" : "text-ink-600")} title={x.error ?? undefined}>
                              <StatusDot status={x.status} /> {sourceLabel(x.source)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="tabular px-3 py-2.5 text-right text-ink-900">{s.candidates_unique}</td>
                      <td className="tabular px-3 py-2.5 text-right text-ink-600">{s.excluded_official}</td>
                      <td className="tabular px-3 py-2.5 text-[11.5px] text-ink-600">
                        <span className="text-ink-900">{s.findings_new}</span> new · {s.findings_changed} changed · {s.findings_recurring} recurring
                        {(s.findings_missing ?? 0) > 0 && <> · {s.findings_missing} missing</>}
                        {s.findings_resolved > 0 && <> · {s.findings_resolved} resolved</>}
                        {(s.findings_unverified ?? 0) > 0 && <span className="text-med"> · {s.findings_unverified} unverified</span>}
                      </td>
                      <td className="py-2.5 pr-4 pl-3 text-ink-500" title={dateTime(s.started_at ?? s.created_at)}>
                        {relTime(s.started_at ?? s.created_at)}
                        {s.duration_ms != null && <div className="text-[11px] text-ink-400">{duration(s.duration_ms)}</div>}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
        {data && data.length === 0 && (
          <EmptyState icon={<History className="size-5" />} title={filtered ? "No scans match these filters" : "No scans yet"} description={filtered ? "Try a wider date range or clear the filters." : "Use “Scan now” in the top bar, or set up a schedule on the brand’s Monitoring tab."} />
        )}
        {total > PAGE && (
          <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2 text-[12px] text-ink-500">
            <span className="tabular">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} of {total}</span>
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

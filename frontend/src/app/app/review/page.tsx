"use client";

import { ArrowUpRight, Flag, PartyPopper, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, ScoreMeter, SourceTypeBadge, StatusBadge } from "@/components/app/bits";
import { useBrands, useScans } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, ErrorState, Kbd, PageHeader, Segmented, Select, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { GROUP_LABELS, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Finding, Paged } from "@/lib/types";

type Scope = "brand" | "all";
type StatusFilter = "outstanding" | "open" | "escalated";
const LEVELS = ["critical", "high", "medium", "low"] as const;
const STATUSES: Record<StatusFilter, string[]> = { outstanding: ["open", "escalated"], open: ["open"], escalated: ["escalated"] };

interface Summary { open_by_level: Record<string, number>; open_total: number; escalated: number; oldest_open_at: string | null; decided_last_7_days: number; decided_by_me_last_7_days: number }

export default function ReviewPage() {
  const { selected, reloadBrands } = useBrands();
  const { version } = useScans();
  const toast = useToast();
  const router = useRouter();
  const [scope, setScope] = useState<Scope>("brand");
  const [levels, setLevels] = useState<string[]>(["critical", "high", "medium"]);
  const [source, setSource] = useState("");
  const [statusF, setStatusF] = useState<StatusFilter>("outstanding");
  const brandId = scope === "brand" ? selected?.id : undefined;
  const { data, error, loading, reload, setData } = useApi<Paged<Finding>>(scope === "all" || selected ? "/findings" : null, {
    brand_id: brandId,
    status: STATUSES[statusF],
    level: levels.length ? levels : [...LEVELS],
    source: source ? [source] : undefined,
    sort: "risk",
    limit: 100,
  });
  const { data: summary, reload: reloadSummary } = useApi<Summary>("/findings/review-summary", { brand_id: brandId });
  useEffect(() => setIdx(0), [scope, levels, source, statusF]);
  const [idx, setIdx] = useState(0);
  const [detail, setDetail] = useState<Finding | null>(null);
  const [busy, setBusy] = useState(false);
  const items = data?.items ?? [];
  const current = items[Math.min(idx, items.length - 1)];

  useEffect(() => {
    if (version) {
      reload(true);
      reloadSummary(true);
    }
  }, [version, reload, reloadSummary]);

  useEffect(() => {
    setDetail(null);
    if (!current) return;
    let cancelled = false;
    api<Finding>(`/findings/${current.id}`).then((d) => !cancelled && setDetail(d)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = useCallback(
    async (action: "confirm" | "mark_safe" | "escalate") => {
      if (!current || busy) return;
      if (action === "escalate" && current.status === "escalated") return;
      setBusy(true);
      try {
        const updated = await api<Finding>(`/findings/${current.id}/decision`, { method: "POST", body: { action, note: "" } });
        const stillListed = STATUSES[statusF].includes(updated.status);
        setData((d) => (d ? (stillListed
          ? { ...d, items: d.items.map((x) => (x.id === current.id ? { ...x, status: updated.status } : x)) }
          : { total: d.total - 1, items: d.items.filter((x) => x.id !== current.id) }) : d));
        toast({ tone: "success", title: `${{ confirm: "Confirmed", mark_safe: "Marked legitimate", escalate: "Marked for further review" }[action]}: ${current.candidate.name}` });
        reloadBrands();
        reloadSummary(true);
      } catch (e) {
        toast({ tone: "error", title: "Could not save decision", description: (e as Error).message });
      } finally {
        setBusy(false);
      }
    },
    [current, busy, setData, toast, reloadBrands, reloadSummary, statusF],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, items.length - 1)); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
      else if (e.key === "c") decide("confirm");
      else if (e.key === "s") decide("mark_safe");
      else if (e.key === "e") decide("escalate");
      else if (e.key === "Enter" && current) router.push(`/app/investigations/${current.id}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items.length, decide, current, router]);

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Investigate"
        title="Review Queue"
        description="Findings that still need a decision, ordered by heuristic risk. Confirm a potential impersonation, mark it legitimate, or flag it for further review. Every decision is saved to the audit trail."
        actions={<Segmented label="Brand scope" value={scope} onChange={setScope} options={[{ value: "brand", label: selected ? selected.name : "This brand" }, { value: "all", label: "All brands" }]} />}
      />
      {summary && (
        <Card className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-[12px]">
          <span className="font-medium text-ink-900"><span className="tabular text-[15px]">{summary.open_total}</span> outstanding</span>
          {LEVELS.map((l) => summary.open_by_level[l] > 0 && <span key={l} className="text-ink-600"><RiskBadge level={l} /> <span className="tabular">{summary.open_by_level[l]}</span></span>)}
          {summary.escalated > 0 && <span className="text-ink-600"><StatusBadge status="escalated" /> <span className="tabular">{summary.escalated}</span></span>}
          {summary.oldest_open_at && <span className="text-ink-500">oldest waiting {relTime(summary.oldest_open_at)}</span>}
          <span className="ml-auto text-ink-500">{summary.decided_last_7_days} decided in 7 days · {summary.decided_by_me_last_7_days} by you</span>
        </Card>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Severity" className="flex gap-1">
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
        <Select aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)} className="h-8 w-auto text-[12.5px]">
          <option value="">All sources</option>
          {["bluesky", "mastodon", "apple_app_store", "google_play"].map((x) => <option key={x} value={x}>{sourceLabel(x)}</option>)}
        </Select>
        <Select aria-label="Review status" value={statusF} onChange={(e) => setStatusF(e.target.value as StatusFilter)} className="h-8 w-auto text-[12.5px]">
          <option value="outstanding">Needs review + further review</option>
          <option value="open">Needs review</option>
          <option value="escalated">Further review only</option>
        </Select>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-[11.5px] text-ink-500">
        <span className="inline-flex items-center gap-1"><Kbd>J</Kbd><Kbd>K</Kbd> move</span>
        <span className="inline-flex items-center gap-1"><Kbd>C</Kbd> confirm</span>
        <span className="inline-flex items-center gap-1"><Kbd>S</Kbd> mark legitimate</span>
        <span className="inline-flex items-center gap-1"><Kbd>E</Kbd> further review</span>
        <span className="inline-flex items-center gap-1"><Kbd>↵</Kbd> open investigation</span>
      </div>
      {error && <ErrorState error={error} onRetry={() => reload()} />}
      {loading && !data ? (
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState icon={<PartyPopper className="size-5" />} title="Nothing to review with these filters" description={levels.includes("low") ? "No outstanding findings match. Try another source, status or brand scope." : "No outstanding medium-or-higher findings match. Include “low” for weak name-only matches."} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[380px_1fr] [&>*]:min-w-0">
          <Card className="overflow-hidden">
            <div className="border-b border-ink-150 px-4 py-2 text-[11.5px] text-ink-500 tabular">{data?.total} matching</div>
            <ul role="listbox" aria-label="Findings to review" className="scrollbar-thin max-h-[68vh] divide-y divide-ink-150 overflow-y-auto">
              {items.map((f, i) => (
                <li key={f.id} role="option" aria-selected={i === idx}>
                  <button onClick={() => setIdx(i)} className={cx("flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors", i === idx ? "bg-teal-100/50" : "hover:bg-white")}>
                    <Avatar url={f.candidate.avatar_url} name={f.candidate.name} size={28} square={f.candidate.kind === "app"} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12.5px] font-medium text-ink-900">{f.candidate.name}</div>
                      <div className="flex items-center gap-1 text-[11px] text-ink-500">
                        <PlatformGlyph platform={f.candidate.platform} className="size-3" /> {sourceLabel(f.candidate.platform)}
                        {scope === "all" && <span className="truncate">· {f.brand_name}</span>}
                        {f.status === "escalated" && <span className="text-teal-700">· further review</span>}
                      </div>
                    </div>
                    <RiskBadge level={f.risk_level} score={f.risk_score} />
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {current && (
            <Card className="p-5" key={current.id}>
              <div className="flex flex-wrap items-start gap-4">
                <Avatar url={current.candidate.avatar_url} name={current.candidate.name} size={48} square={current.candidate.kind === "app"} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-[17px] font-semibold text-ink-950">{current.candidate.name}</h2>
                    <SourceTypeBadge type={current.candidate.source_type} />
                    <ChangeBadge state={current.change_state} />
                  </div>
                  <div className="mt-0.5 text-[12px] text-ink-500">
                    {sourceLabel(current.candidate.platform)} · {current.candidate.handle ? `@${current.candidate.handle}` : current.candidate.publisher_name ?? current.candidate.external_id} · first seen {relTime(current.candidate.first_observed_at)}
                  </div>
                </div>
                <RiskBadge level={current.risk_level} score={current.risk_score} />
              </div>
              <div className="mt-4 text-[13px] font-medium text-ink-900">{current.classification}</div>
              <p className="mt-1 text-[12.5px] leading-relaxed text-ink-700">{current.explanation}</p>
              {current.candidate.description && (
                <p className="mt-3 line-clamp-4 rounded-md border border-ink-150 bg-white px-3 py-2 text-[12.5px] leading-relaxed text-ink-700">{current.candidate.description}</p>
              )}
              <div className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                {detail?.signals
                  ? Object.entries(detail.signals.groups).map(([g, v]) => (
                      <div key={g} className="flex items-center justify-between gap-3 text-[12px]">
                        <span className={cx("text-ink-600", current.corroborating_groups.includes(g) && "font-medium text-ink-900")}>
                          {GROUP_LABELS[g]}
                          {current.corroborating_groups.includes(g) && " ✓"}
                        </span>
                        <ScoreMeter value={v ?? 0} evaluated={v !== null} />
                      </div>
                    ))
                  : Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-4" />)}
              </div>
              {detail?.reasons && detail.reasons.length > 0 && (
                <ul className="mt-4 list-disc space-y-0.5 pl-5 text-[12px] text-ink-600 marker:text-ink-300">
                  {detail.reasons.slice(0, 6).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
              <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-ink-150 pt-4">
                <Button variant="primary" icon={<ShieldX className="size-3.5" />} loading={busy} onClick={() => decide("confirm")}>Confirm <Kbd>C</Kbd></Button>
                <Button icon={<ShieldCheck className="size-3.5" />} disabled={busy} onClick={() => decide("mark_safe")}>Mark legitimate <Kbd>S</Kbd></Button>
                {current.status !== "escalated" && <Button variant="ghost" icon={<Flag className="size-3.5" />} disabled={busy} onClick={() => decide("escalate")}>Further review <Kbd>E</Kbd></Button>}
                <Link href={`/app/investigations/${current.id}`} className="ml-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-teal-700 hover:underline">
                  Full investigation <ArrowUpRight className="size-3.5" />
                </Link>
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import { ArrowDown, ArrowUp, Download, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { buildQuery } from "@/lib/api";
import { relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Finding, Paged } from "@/lib/types";
import { Button, Card, EmptyState, ErrorState, Input, Select, Skeleton, cx } from "../ui";
import { Avatar, ChangeBadge, PlatformGlyph, RiskBadge, SourceTypeBadge, StatusBadge } from "./bits";
import { useBrands, useScans } from "./providers";

const LEVELS = ["critical", "high", "medium", "low"] as const;
const PAGE = 25;

type SortKey = "risk" | "name" | "last_seen" | "first_seen" | "updated";

export function FindingsExplorer({ kind, sourceOptions, defaultLevels }: { kind?: "account" | "app"; sourceOptions: { value: string; label: string }[]; defaultLevels?: string[] }) {
  const { selected } = useBrands();
  const { version } = useScans();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [q, setQ] = useState(params.get("q") ?? "");
  const [debouncedQ, setDebouncedQ] = useState(q);
  const levels = params.getAll("level").length ? params.getAll("level") : defaultLevels ?? [];
  const status = params.get("status") ?? "";
  const change = params.get("change") ?? "";
  const source = params.get("source") ?? "";
  const sourceType = params.get("source_type") ?? "";
  const sort = (params.get("sort") as SortKey) ?? "risk";
  const order = params.get("order") ?? "desc";
  const page = Number(params.get("page") ?? "0");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const setParam = (updates: Record<string, string | string[] | null>) => {
    const p = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(updates)) {
      p.delete(k);
      if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
      else if (v) p.set(k, v);
    }
    if (!("page" in updates)) p.delete("page");
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };

  useEffect(() => {
    if ((params.get("q") ?? "") !== debouncedQ) setParam({ q: debouncedQ || null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const query = useMemo(
    () => ({
      brand_id: selected?.id,
      kind,
      level: levels,
      status: status ? [status] : undefined,
      change_state: change ? [change] : undefined,
      source: source ? [source] : undefined,
      source_type: sourceType || undefined,
      q: debouncedQ || undefined,
      sort,
      order,
      limit: PAGE,
      offset: page * PAGE,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selected?.id, kind, levels.join(","), status, change, source, sourceType, debouncedQ, sort, order, page],
  );
  const { data, error, loading, reload } = useApi<Paged<Finding>>(selected ? "/findings" : null, query);
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);

  const exportHref = `/api/findings/export.csv${buildQuery({ ...query, limit: undefined, offset: undefined, sort: undefined, order: undefined })}`;
  const filtersActive = levels.length > 0 || status || change || source || sourceType || debouncedQ;

  const SortHead = ({ k, children, className }: { k: SortKey; children: React.ReactNode; className?: string }) => {
    const activeSort = sort === k;
    return (
      <th className={cx("px-3 py-2 font-medium", className)} aria-sort={activeSort ? (order === "asc" ? "ascending" : "descending") : "none"}>
        <button
          className={cx("inline-flex items-center gap-1 hover:text-ink-900", activeSort && "text-ink-900")}
          onClick={() => setParam({ sort: k, order: activeSort && order === "desc" ? "asc" : "desc" })}
        >
          {children}
          {activeSort && (order === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
        </button>
      </th>
    );
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-150 px-3 py-2.5">
        <div className="relative w-full sm:w-60">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-400" />
          <Input aria-label="Search findings" placeholder="Search name, handle, ID…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8" />
        </div>
        <div role="group" aria-label="Risk level" className="flex items-center gap-1">
          {LEVELS.map((l) => {
            const on = levels.includes(l);
            return (
              <button
                key={l}
                aria-pressed={on}
                onClick={() => setParam({ level: on ? levels.filter((x) => x !== l) : [...levels, l] })}
                className={cx(
                  "h-8 rounded-md border px-2.5 text-[12px] font-medium capitalize transition-colors",
                  on ? "border-ink-800 bg-ink-800 text-white" : "border-ink-200 bg-white text-ink-600 hover:border-ink-300",
                )}
              >
                {l}
              </button>
            );
          })}
        </div>
        <Select aria-label="Status" value={status} onChange={(e) => setParam({ status: e.target.value || null })} className="h-8 w-auto text-[12.5px]">
          <option value="">Any status</option>
          <option value="open">Needs review</option>
            <option value="escalated">Further review</option>
          <option value="confirmed">Confirmed</option>
          <option value="safe">Marked legitimate</option>
          <option value="resolved">No longer observed</option>
        </Select>
        <Select aria-label="Change" value={change} onChange={(e) => setParam({ change: e.target.value || null })} className="h-8 w-auto text-[12.5px]">
          <option value="">Any change</option>
          <option value="new">New</option>
          <option value="changed">Changed</option>
          <option value="recurring">Recurring</option>
          <option value="resolved">Not seen</option>
        </Select>
        <Select aria-label="Source" value={source} onChange={(e) => setParam({ source: e.target.value || null })} className="h-8 w-auto text-[12.5px]">
          <option value="">All sources</option>
          {sourceOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>
        <Select aria-label="Data type" value={sourceType} onChange={(e) => setParam({ source_type: e.target.value || null })} className="h-8 w-auto text-[12.5px]">
          <option value="">Live, simulated & imported</option>
          <option value="live">Live only</option>
          <option value="simulated">Simulated only</option>
          <option value="imported">Imported only</option>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          {filtersActive && (
            <Button size="sm" variant="ghost" onClick={() => { setQ(""); router.replace(pathname, { scroll: false }); }}>
              Clear filters
            </Button>
          )}
          <a href={exportHref} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-ink-200 bg-paper px-2.5 text-[12.5px] font-medium text-ink-800 shadow-card hover:border-ink-300" download>
            <Download className="size-3.5" /> CSV
          </a>
        </div>
      </div>
      {error && <div className="p-3"><ErrorState error={error} onRetry={() => reload()} /></div>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-[12.5px]">
          <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
            <tr>
              <SortHead k="name" className="pl-4">Candidate</SortHead>
              <th className="px-3 py-2 font-medium">Source</th>
              <SortHead k="risk">Risk</SortHead>
              <th className="px-3 py-2 font-medium">Classification</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <SortHead k="last_seen" className="pr-4">Last seen</SortHead>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-150">
            {loading && !data
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={6} className="px-4 py-3"><Skeleton className="h-6" /></td>
                  </tr>
                ))
              : data?.items.map((f) => (
                  <tr key={f.id} className="group cursor-pointer transition-colors hover:bg-white" onClick={() => router.push(`/app/investigations/${f.id}`)}>
                    <td className="py-2.5 pr-3 pl-4">
                      <div className="flex items-center gap-2.5">
                        <Avatar url={f.candidate.avatar_url} name={f.candidate.name} size={30} square={f.candidate.kind === "app"} />
                        <div className="min-w-0">
                          <Link href={`/app/investigations/${f.id}`} onClick={(e) => e.stopPropagation()} className="block max-w-[260px] truncate font-medium text-ink-900 group-hover:underline">
                            {f.candidate.name}
                          </Link>
                          <div className="max-w-[260px] truncate text-[11.5px] text-ink-500">
                            {f.candidate.kind === "app" ? f.candidate.publisher_name ?? "Unknown publisher" : f.candidate.handle ? `@${f.candidate.handle}` : f.candidate.external_id}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-col items-start gap-1">
                        <span className="inline-flex items-center gap-1.5 text-ink-700">
                          <PlatformGlyph platform={f.candidate.platform} className="text-ink-500" />
                          {sourceLabel(f.candidate.platform)}
                        </span>
                        <SourceTypeBadge type={f.candidate.source_type} />
                      </div>
                    </td>
                    <td className="px-3 py-2.5"><RiskBadge level={f.risk_level} score={f.risk_score} /></td>
                    <td className="max-w-[300px] px-3 py-2.5">
                      <div className="truncate text-ink-800" title={f.classification}>{f.classification}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        <ChangeBadge state={f.change_state} />
                      </div>
                    </td>
                    <td className="px-3 py-2.5"><StatusBadge status={f.status} level={f.risk_level} /></td>
                    <td className="tabular py-2.5 pr-4 pl-3 text-ink-500" title={f.candidate.last_observed_at}>{relTime(f.candidate.last_observed_at)}</td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
      {data && data.items.length === 0 && (
        <EmptyState
          icon={<SearchX className="size-5" />}
          title={filtersActive ? "No findings match these filters" : "No findings yet"}
          description={filtersActive ? "Try clearing a filter." : "Run a scan to collect candidates from the enabled sources."}
        />
      )}
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2.5 text-[12px] text-ink-500">
          <span className="tabular">
            {page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={page === 0} onClick={() => setParam({ page: String(page - 1) })}>Previous</Button>
            <Button size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setParam({ page: String(page + 1) })}>Next</Button>
          </div>
        </div>
      )}
      {data && data.total > 0 && data.total <= PAGE && (
        <div className="border-t border-ink-150 px-4 py-2 text-[11.5px] text-ink-400 tabular">{data.total} finding{data.total === 1 ? "" : "s"}</div>
      )}
    </Card>
  );
}

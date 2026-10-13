"use client";

import { Gavel } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PlatformGlyph, RiskBadge } from "@/components/app/bits";
import { TAKEDOWN_STATUS, VERIFICATION, type TakedownCase } from "@/components/app/takedown-card";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Filter = "open" | "closed" | "all";
const OPEN = ["draft", "reported", "acknowledged"];

export default function TakedownsPage() {
  const [filter, setFilter] = useState<Filter>("open");
  const { data, error, loading, reload } = useApi<{ items: TakedownCase[]; counts: Record<string, number> }>("/takedowns");
  const items = (data?.items ?? []).filter((c) => (filter === "all" ? true : filter === "open" ? OPEN.includes(c.status) : !OPEN.includes(c.status)));
  const count = (s: string[]) => s.reduce((n, k) => n + (data?.counts[k] ?? 0), 0);

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Investigate"
        title="Takedowns"
        description="Reports prepared for confirmed impersonations and their outcome. You file each report through the platform’s own route; later scans check whether the account or listing is still visible."
        actions={<Segmented label="Case status" value={filter} onChange={setFilter} options={[
          { value: "open", label: "Open", count: count(OPEN) },
          { value: "closed", label: "Closed", count: count(["removed", "rejected", "withdrawn"]) },
          { value: "all", label: "All", count: data?.items.length },
        ]} />}
      />
      {error && <ErrorState error={error} onRetry={() => reload()} />}
      <Card className="overflow-hidden">
        {loading && !data ? (
          <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : items.length === 0 ? (
          <EmptyState icon={<Gavel className="size-5" />} title={filter === "open" ? "No open takedown cases" : "No cases"}
            description="Confirm an impersonation on its investigation page, then open a takedown case there." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-[12.5px]">
              <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
                <tr>
                  <th className="py-2 pr-3 pl-4 font-medium">Account / listing</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Reference</th>
                  <th className="px-3 py-2 font-medium">Re-check</th>
                  <th className="py-2 pr-4 pl-3 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-150">
                {items.map((c) => (
                  <tr key={c.id} className="hover:bg-white">
                    <td className="py-2.5 pr-3 pl-4">
                      <Link href={`/app/investigations/${c.finding_id}`} className="font-medium text-teal-700 hover:underline">{c.candidate?.name}</Link>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-ink-500">
                        <PlatformGlyph platform={c.platform} /> {sourceLabel(c.platform)} · {c.brand_name}
                        {c.risk_level && <RiskBadge level={c.risk_level as "low"} />}
                        {c.candidate?.source_type === "simulated" && <Badge tone="med">Synthetic</Badge>}
                      </div>
                    </td>
                    <td className="px-3 py-2.5"><Badge tone={TAKEDOWN_STATUS[c.status].tone} dot>{TAKEDOWN_STATUS[c.status].label}</Badge></td>
                    <td className="px-3 py-2.5 font-mono text-[11.5px] text-ink-700">{c.reference || <span className="font-sans text-ink-400">—</span>}</td>
                    <td className={`px-3 py-2.5 text-[11.5px] ${VERIFICATION[c.verification].className}`}>{c.status === "draft" ? <span className="text-ink-400">—</span> : VERIFICATION[c.verification].label}</td>
                    <td className="py-2.5 pr-4 pl-3 text-ink-500">{relTime((c as TakedownCase & { updated_at?: string }).updated_at ?? c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

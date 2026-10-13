"use client";

import { Beaker, Building2, MoreHorizontal, Plus, Search, SearchX, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { StatusDot } from "@/components/app/bits";
import { DeleteBrandDialog } from "@/components/app/delete-brand";
import { useBrands, useScans } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, ButtonLink, Card, EmptyState, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { Brand } from "@/lib/types";

function matches(b: Brand, q: string) {
  if (!q) return true;
  const hay = [b.name, ...b.aliases, ...b.official_domains, ...b.keywords, ...b.official_accounts.map((a) => a.handle), ...b.official_apps.map((a) => `${a.app_id} ${a.name ?? ""}`)]
    .join(" ")
    .toLowerCase();
  return q.toLowerCase().split(/\s+/).every((t) => hay.includes(t));
}

function RowMenu({ brand, onDelete }: { brand: Brand; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button aria-label={`Actions for ${brand.name}`} aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid size-8 place-items-center rounded-md text-ink-500 hover:bg-ink-100 hover:text-ink-900">
        <MoreHorizontal className="size-4" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-md border border-ink-150 bg-paper py-1 shadow-pop animate-fade-in" role="menu">
          <Link role="menuitem" href={`/app/brands/${brand.id}`} className="block px-3 py-1.5 text-[12.5px] text-ink-800 hover:bg-ink-50">Edit profile</Link>
          <Link role="menuitem" href={`/app/brands/${brand.id}?tab=registry`} className="block px-3 py-1.5 text-[12.5px] text-ink-800 hover:bg-ink-50">Asset registry</Link>
          <button role="menuitem" onClick={() => { setOpen(false); onDelete(); }} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] text-crit hover:bg-crit-bg">
            <Trash2 className="size-3.5" /> Delete…
          </button>
        </div>
      )}
    </div>
  );
}

export default function BrandsPage() {
  const { brands, loading, select, reloadBrands } = useBrands();
  const { active } = useScans();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [deleting, setDeleting] = useState<Brand | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const hasDemo = brands.some((b) => b.is_demo);
  const shown = brands.filter((b) => matches(b, q.trim()));

  const loadDemo = async () => {
    setLoadingDemo(true);
    try {
      const b = await api<Brand>("/demo/brand", { method: "POST" });
      await reloadBrands();
      select(b.id);
      toast({ tone: "success", title: "Sample brand added", description: "“Northvale Pay” is fictional and scans synthetic data only." });
    } catch (e) {
      toast({ tone: "error", title: "Could not add the sample brand", description: (e as Error).message });
    } finally {
      setLoadingDemo(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Configure"
        title="Brand Profiles"
        description="Each profile defines what to look for and which assets are official. Scans always use the profile of the brand being scanned."
        actions={
          <>
            {!hasDemo && !loading && <Button icon={<Beaker className="size-3.5" />} loading={loadingDemo} onClick={loadDemo}>Add sample brand</Button>}
            <ButtonLink href="/app/brands/new" variant="primary" icon={<Plus className="size-3.5" />}>New brand</ButtonLink>
          </>
        }
      />
      {loading ? (
        <Skeleton className="h-48" />
      ) : !brands.length ? (
        <Card>
          <EmptyState
            icon={<Building2 className="size-5" />}
            title="No brand profiles yet"
            description="Create a profile for a brand you protect, or add the fictional sample brand to explore with synthetic data."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <ButtonLink href="/app/brands/new" variant="primary">New brand</ButtonLink>
                <Button loading={loadingDemo} onClick={loadDemo}>Add sample brand</Button>
              </div>
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-ink-150 px-3 py-2.5">
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-400" />
              <Input aria-label="Search brands" placeholder="Search names, domains, handles, app IDs…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 pl-8" />
            </div>
            <span className="tabular text-[12px] text-ink-500">{q ? `${shown.length} of ${brands.length}` : `${brands.length} brand${brands.length === 1 ? "" : "s"}`}</span>
          </div>
          {shown.length === 0 ? (
            <EmptyState icon={<SearchX className="size-5" />} title={`No brands match “${q}”`} action={<Button size="sm" onClick={() => setQ("")}>Clear search</Button>} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12.5px] md:min-w-[760px]">
                <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
                  <tr>
                    <th scope="col" className="py-2 pr-3 pl-4 font-medium">Brand</th>
                    <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Official assets</th>
                    <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Needs review</th>
                    <th scope="col" className="px-3 py-2 font-medium">Last scan</th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">Schedule</th>
                    <th scope="col" className="relative py-2 pr-4 pl-3"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-150">
                  {shown.map((b) => {
                    const running = active.find((s) => s.brand_id === b.id);
                    const last = b.stats.last_scan;
                    return (
                      <tr key={b.id} className="hover:bg-white">
                        <td className="py-2.5 pr-3 pl-4">
                          <Link href={`/app/brands/${b.id}`} onClick={() => select(b.id)} className="flex min-w-0 items-center gap-3">
                            <span className="grid size-9 shrink-0 place-items-center overflow-hidden rounded-md border border-ink-150 bg-white">
                              {b.has_logo ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img src={`/api/brands/${b.id}/logo?v=${b.logo_phash}`} alt="" className="size-full object-contain" />
                              ) : (
                                <span className="text-[13px] font-semibold text-ink-500">{b.name[0]}</span>
                              )}
                            </span>
                            <span className="min-w-0">
                              <span className="flex items-center gap-2 font-medium text-ink-900">
                                <span className="truncate hover:underline">{b.name}</span>
                                {b.is_demo && <Badge tone="med">Sample</Badge>}
                              </span>
                              <span className="block max-w-[260px] truncate text-[11.5px] text-ink-500">{b.official_domains[0] ?? (b.aliases.length ? `Also: ${b.aliases.join(", ")}` : "No domains yet")}</span>
                              <span className="tabular block text-[11.5px] text-ink-500 md:hidden">{b.official_accounts.length + b.official_apps.length + b.official_domains.length} official assets · {b.stats.open_review ?? 0} to review</span>
                            </span>
                          </Link>
                        </td>
                        <td className="tabular hidden px-3 py-2.5 text-ink-700 md:table-cell">
                          {b.official_accounts.length} accounts · {b.official_apps.length} apps · {b.official_domains.length} domains
                          {!b.has_logo && <div className="text-[11.5px] text-ink-400">No logo</div>}
                        </td>
                        <td className="tabular hidden px-3 py-2.5 md:table-cell">
                          {b.stats.open_review ? <Link href="/app/review" onClick={() => select(b.id)} className="font-medium text-ink-900 hover:underline">{b.stats.open_review}</Link> : <span className="text-ink-400">0</span>}
                        </td>
                        <td className="px-3 py-2.5">
                          {running ? (
                            <span className="inline-flex items-center gap-1.5 text-teal-700"><StatusDot status="running" /> Scanning {Math.round(running.progress * 100)}%</span>
                          ) : last ? (
                            <Link href={`/app/scans/${last.id}`} className="inline-flex items-center gap-1.5 text-ink-700 hover:underline">
                              <StatusDot status={last.status} /> <span className="capitalize">{last.status}</span> <span className="text-ink-500">· {relTime(last.finished_at ?? last.created_at)}</span>
                            </Link>
                          ) : (
                            <span className="text-ink-400">Never scanned</span>
                          )}
                        </td>
                        <td className="hidden px-3 py-2.5 text-ink-600 lg:table-cell">{b.schedule ? (b.schedule.state === "active" ? b.schedule.description : b.schedule.state === "paused" ? "Paused" : "Disabled") : "Manual only"}</td>
                        <td className="py-2.5 pr-4 pl-3 text-right"><RowMenu brand={b} onDelete={() => setDeleting(b)} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      {deleting && (
        <DeleteBrandDialog
          brand={deleting}
          open
          onClose={() => setDeleting(null)}
          onDeleted={async () => {
            setDeleting(null);
            await reloadBrands();
          }}
        />
      )}
    </div>
  );
}

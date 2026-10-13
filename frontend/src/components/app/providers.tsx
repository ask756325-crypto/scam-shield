"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Brand, Scan, Session } from "@/lib/types";
import { useToast } from "../toast";

// ---------------------------------------------------------------- Session

interface SessionCtxT {
  session: Session | null;
  refresh: () => Promise<void>;
}
const SessionCtx = createContext<SessionCtxT>({ session: null, refresh: async () => {} });
export const useSession = () => useContext(SessionCtx);

// ---------------------------------------------------------------- Brands

interface BrandCtxT {
  brands: Brand[];
  loading: boolean;
  selected: Brand | null;
  selectedId: number | null;
  select: (id: number | null) => void;
  reloadBrands: () => Promise<void>;
}
const BrandCtx = createContext<BrandCtxT>({ brands: [], loading: true, selected: null, selectedId: null, select: () => {}, reloadBrands: async () => {} });
export const useBrands = () => useContext(BrandCtx);

// ---------------------------------------------------------------- Scans

interface ScanCtxT {
  active: Scan[];
  startScan: (brandId: number, sources?: string[]) => Promise<Scan | null>;
  track: (scanId: number) => void;
  lastFinished: Scan | null;
  /** Increments whenever a tracked scan finishes, so pages can refetch. */
  version: number;
}
const ScanCtx = createContext<ScanCtxT>({ active: [], startScan: async () => null, track: () => {}, lastFinished: null, version: 0 });
export const useScans = () => useContext(ScanCtx);

const STORAGE_KEY = "ss.selectedBrand";

export function AppProviders({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [session, setSession] = useState<Session | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandsLoading, setBrandsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [active, setActive] = useState<Scan[]>([]);
  const [lastFinished, setLastFinished] = useState<Scan | null>(null);
  const [version, setVersion] = useState(0);
  const tracked = useRef<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setSession(await api<Session>("/auth/me"));
    } catch {
      /* api() redirects on 401 */
    }
  }, []);

  const reloadBrands = useCallback(async () => {
    try {
      const list = await api<Brand[]>("/brands");
      setBrands(list);
      setSelectedId((cur) => {
        let stored: number | null = cur;
        if (stored === null) {
          try {
            const raw = localStorage.getItem(STORAGE_KEY);
            stored = raw ? Number(raw) : null;
          } catch {}
        }
        if (stored !== null && list.some((b) => b.id === stored)) return stored;
        return list[0]?.id ?? null;
      });
    } finally {
      setBrandsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    reloadBrands();
    // Pick up scans already running (e.g. scheduled scans or another tab).
    api<Scan[]>("/scans", { query: { limit: 10 } })
      .then((scans) => scans.filter((s) => s.status === "queued" || s.status === "running").forEach((s) => tracked.current.add(s.id)))
      .catch(() => {});
  }, [refresh, reloadBrands]);

  const select = useCallback((id: number | null) => {
    setSelectedId(id);
    try {
      if (id === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, String(id));
    } catch {}
  }, []);

  // Poll tracked scans; real progress comes from the backend's completed work units.
  useEffect(() => {
    const tick = async () => {
      const ids = Array.from(tracked.current);
      if (!ids.length) {
        setActive((a) => (a.length ? [] : a));
        return;
      }
      const results = await Promise.all(ids.map((id) => api<Scan>(`/scans/${id}`).catch(() => null)));
      const still: Scan[] = [];
      results.forEach((s, i) => {
        if (!s) {
          tracked.current.delete(ids[i]);
          return;
        }
        if (s.status === "queued" || s.status === "running") still.push(s);
        else {
          tracked.current.delete(s.id);
          setLastFinished(s);
          setVersion((v) => v + 1);
          const n = s.findings_new;
          if (s.status === "failed") toast({ tone: "error", title: `Scan failed — ${s.brand_name}`, description: s.error ?? "All sources failed." });
          else
            toast({
              tone: s.status === "partial" ? "info" : "success",
              title: `Scan ${s.status === "partial" ? "finished with source errors" : "complete"} — ${s.brand_name}`,
              description: `${s.candidates_unique} candidates · ${n} new · ${s.findings_changed} changed · ${s.findings_resolved} resolved`,
            });
          reloadBrands();
        }
      });
      setActive(still);
    };
    tick();
    const id = setInterval(tick, 1200);
    return () => clearInterval(id);
  }, [toast, reloadBrands]);

  const track = useCallback((id: number) => {
    tracked.current.add(id);
  }, []);

  const starting = useRef<Set<number>>(new Set());
  const startScan = useCallback(
    async (brandId: number, sources?: string[]) => {
      // Synchronous guard: a double-click fires twice before React re-renders the disabled button.
      if (starting.current.has(brandId)) return null;
      starting.current.add(brandId);
      try {
        const s = await api<Scan>(`/brands/${brandId}/scans`, { method: "POST", body: sources ? { sources } : {} });
        tracked.current.add(s.id);
        setActive((a) => [...a.filter((x) => x.id !== s.id), s]);
        return s;
      } catch (e) {
        const err = e as ApiError;
        const runningId = (err.data as { detail?: { scan_id?: number } })?.detail?.scan_id;
        if (runningId) tracked.current.add(runningId);
        if (runningId) toast({ tone: "info", title: "A scan is already running for this brand", description: "Showing its progress instead." });
        else toast({ tone: "error", title: "Could not start scan", description: err.message });
        return null;
      } finally {
        starting.current.delete(brandId);
      }
    },
    [toast],
  );

  const selected = useMemo(() => brands.find((b) => b.id === selectedId) ?? null, [brands, selectedId]);

  return (
    <SessionCtx.Provider value={{ session, refresh }}>
      <BrandCtx.Provider value={{ brands, loading: brandsLoading, selected, selectedId, select, reloadBrands }}>
        <ScanCtx.Provider value={{ active, startScan, track, lastFinished, version }}>{children}</ScanCtx.Provider>
      </BrandCtx.Provider>
    </SessionCtx.Provider>
  );
}

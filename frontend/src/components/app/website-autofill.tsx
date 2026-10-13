"use client";

import { Check, Globe, Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { OfficialAccount, OfficialApp } from "@/lib/types";
import { Badge, Button, Card, Input, cx } from "../ui";
import type { BrandPayload } from "./brand-form";

export interface AutofillDraft {
  source_url: string;
  fields: { name?: string; description?: string; website_url?: string };
  official_domains: string[];
  official_accounts: { platform: string; handle: string; profile_url: string | null; external_id: string | null }[];
  official_apps: { store: string; name?: string | null; app_id?: string; track_id?: string | null; publisher_id?: string | null; publisher_name?: string | null; url?: string | null }[];
  logo: { filename: string; data_base64: string; width: number; height: number; source: string } | null;
  found: string[];
  missing: string[];
  warnings: string[];
}

/**
 * Fills the form from a public website. It only fills what is empty and adds what the site declares; the analyst
 * still reviews everything and presses Save. Nothing is saved from here.
 */
export function WebsiteAutofill({
  current, onApply, onLogo, hasLogo,
}: {
  current: BrandPayload;
  onApply: (patch: Partial<BrandPayload>) => void;
  onLogo: (file: File) => void;
  hasLogo: boolean;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AutofillDraft | null>(null);

  const fetchAndFill = async () => {
    setBusy(true);
    setError(null);
    try {
      const d = await api<AutofillDraft>("/brands/autofill", { method: "POST", body: { url } });
      setDraft(d);
      const patch: Partial<BrandPayload> = {};
      if (!current.name.trim() && d.fields.name) patch.name = d.fields.name;
      if (!current.description.trim() && d.fields.description) patch.description = d.fields.description;
      if (!current.website_url.trim() && d.fields.website_url) patch.website_url = d.fields.website_url;
      const domains = Array.from(new Set([...current.official_domains, ...d.official_domains]));
      if (domains.length !== current.official_domains.length) patch.official_domains = domains;
      const accounts: OfficialAccount[] = [...current.official_accounts];
      for (const a of d.official_accounts) {
        if (!accounts.some((x) => x.platform === a.platform && x.handle.toLowerCase() === a.handle.toLowerCase())) {
          accounts.push({ platform: a.platform, handle: a.handle, profile_url: a.profile_url, external_id: a.external_id });
        }
      }
      if (accounts.length !== current.official_accounts.length) patch.official_accounts = accounts;
      const apps: OfficialApp[] = [...current.official_apps];
      for (const a of d.official_apps) {
        const key = a.store === "apple" ? a.track_id ?? a.app_id : a.app_id;
        if (!apps.some((x) => x.store === a.store && (a.store === "apple" ? x.track_id === key || x.app_id === a.app_id : x.app_id === a.app_id))) {
          apps.push({ store: a.store, name: a.name ?? null, app_id: a.app_id ?? "", track_id: a.track_id ?? null, publisher_id: a.publisher_id ?? null, publisher_name: a.publisher_name ?? null, url: a.url ?? null });
        }
      }
      if (apps.length !== current.official_apps.length) patch.official_apps = apps;
      if (Object.keys(patch).length) onApply(patch);
      if (d.logo && !hasLogo) {
        const bytes = Uint8Array.from(atob(d.logo.data_base64), (c) => c.charCodeAt(0));
        onLogo(new File([bytes], d.logo.filename, { type: "image/png" }));
      }
    } catch (e) {
      setError(e instanceof ApiError ? (e.message || "Could not read that website.") : (e as Error).message);
      setDraft(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-md border border-ink-150 bg-ink-50 text-ink-600"><Sparkles className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold text-ink-900">Autofill from the brand’s website</div>
          <p className="mt-0.5 text-[12px] text-ink-500">
            Paste the official site. ScamShield reads only the public page: name, description, logo, linked social profiles and app-store links.
            It fills empty fields and adds what the site declares. Review the result, then save.
          </p>
          {/* A div, not a <form>: this panel lives inside the brand form and forms cannot nest. */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[16rem] flex-1">
              <Globe className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-400" />
              <Input aria-label="Autofill source website" placeholder="https://www.example.com" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (url.trim() && !busy) fetchAndFill(); } }} className="pl-8" autoComplete="off" />
            </div>
            <Button type="button" variant="primary" onClick={fetchAndFill} disabled={busy || !url.trim()} icon={busy ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}>
              {busy ? "Reading website…" : "Autofill"}
            </Button>
          </div>
          {error && <p role="alert" className="mt-2 text-[12px] text-crit">{error}</p>}
          {draft && (
            <div className="mt-3 space-y-2 rounded-md border border-ink-150 bg-white p-3 text-[12px]">
              <div className="font-medium text-ink-900">Read {draft.source_url}</div>
              <ul className="space-y-1">
                {draft.found.map((f) => (
                  <li key={f} className="flex items-start gap-1.5 text-ink-700"><Check className="mt-0.5 size-3.5 shrink-0 text-forest-600" /> {f}</li>
                ))}
              </ul>
              {draft.missing.length > 0 && (
                <div className={cx("text-ink-500")}>
                  <span className="font-medium text-ink-600">Not found on the site: </span>{draft.missing.join(" · ")}
                </div>
              )}
              {draft.warnings.map((w) => <div key={w} className="text-med">{w}</div>)}
              <Badge tone="teal">Filled into the form below — review, then save</Badge>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

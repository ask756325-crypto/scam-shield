"use client";

import { AlertTriangle, Check, ImageUp, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { Brand, OfficialAccount, OfficialApp } from "@/lib/types";
import { useToast } from "../toast";
import { Button, Card, CardHeader, Field, Input, Select, TagInput, Textarea } from "../ui";

// ---------------------------------------------------------------- payload

export interface BrandPayload {
  name: string;
  aliases: string[];
  description: string;
  website_url: string;
  official_domains: string[];
  keywords: string[];
  additional_identifiers: string[];
  official_accounts: OfficialAccount[];
  official_apps: OfficialApp[];
}

export const EMPTY_BRAND: BrandPayload = {
  name: "",
  aliases: [],
  description: "",
  website_url: "",
  official_domains: [],
  keywords: [],
  additional_identifiers: [],
  official_accounts: [],
  official_apps: [],
};

const PLATFORMS = ["bluesky", "mastodon", "x", "instagram", "facebook", "tiktok", "youtube", "linkedin", "threads", "telegram", "other"];
const SCANNED = new Set(["bluesky", "mastodon"]);

export function brandToPayload(b: Brand): BrandPayload {
  return {
    name: b.name,
    aliases: b.aliases,
    description: b.description,
    website_url: b.website_url ?? "",
    official_domains: b.official_domains,
    keywords: b.keywords,
    additional_identifiers: b.additional_identifiers ?? [],
    official_accounts: b.official_accounts.map(({ platform, handle, profile_url, external_id }) => ({ platform, handle, profile_url: profile_url ?? "", external_id: external_id ?? "" })),
    official_apps: b.official_apps.map(({ store, name, app_id, track_id, publisher_id, publisher_name, url }) => ({
      store, name: name ?? "", app_id, track_id: track_id ?? "", publisher_id: publisher_id ?? "", publisher_name: publisher_name ?? "", url: url ?? "",
    })),
  };
}

/** Rows the user left completely blank are dropped; everything else is sent so the server can validate it. */
function clean(p: BrandPayload) {
  const nul = (v?: string | null) => (v && v.trim() ? v.trim() : null);
  return {
    ...p,
    website_url: nul(p.website_url),
    official_accounts: p.official_accounts
      .filter((a) => a.handle.trim() || a.profile_url?.trim() || a.external_id?.trim())
      .map((a) => ({ ...a, profile_url: nul(a.profile_url), external_id: nul(a.external_id) })),
    official_apps: p.official_apps
      .filter((a) => a.app_id.trim() || a.name?.trim() || a.publisher_id?.trim() || a.url?.trim())
      .map((a) => ({ ...a, name: nul(a.name), track_id: nul(a.track_id), publisher_id: nul(a.publisher_id), publisher_name: nul(a.publisher_name), url: nul(a.url) })),
  };
}
export type CleanBrandPayload = ReturnType<typeof clean>;

/** Server validation → field-path map. Row indices refer to the cleaned list, so map them back. */
function mapErrors(err: ApiError, p: BrandPayload): { fields: Record<string, string>; general: string[] } {
  const fields: Record<string, string> = {};
  const general: string[] = [];
  const list = (err.data as { errors?: { field: string; message: string }[] })?.errors;
  const keptAccounts = p.official_accounts.map((a, i) => (a.handle.trim() || a.profile_url?.trim() || a.external_id?.trim() ? i : -1)).filter((i) => i >= 0);
  const keptApps = p.official_apps.map((a, i) => (a.app_id.trim() || a.name?.trim() || a.publisher_id?.trim() || a.url?.trim() ? i : -1)).filter((i) => i >= 0);
  if (!list?.length) return { fields, general: [err.message] };
  for (const e of list) {
    const m = e.field.match(/^(official_accounts|official_apps)\.(\d+)\.(\w+)/);
    if (m) {
      const real = (m[1] === "official_accounts" ? keptAccounts : keptApps)[Number(m[2])];
      fields[`${m[1]}.${real}.${m[3]}`] = e.message;
    } else if (e.field && /^[a-z_]+(\.\d+)?$/.test(e.field)) {
      fields[e.field.split(".")[0]] = e.message;
    } else general.push(e.message);
  }
  return { fields, general };
}

// ---------------------------------------------------------------- logo

const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** Client-side pre-check mirroring the server limits (the server re-validates and re-encodes). */
export async function checkLogoFile(file: File): Promise<string | null> {
  if (!LOGO_TYPES.includes(file.type)) return "Use a PNG, JPEG, WebP or GIF image. SVG is not accepted.";
  if (file.size > 2 * 1024 * 1024) return `The file is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is 2 MB.`;
  try {
    const bmp = await createImageBitmap(file);
    const { width: w, height: h } = bmp;
    bmp.close();
    if (w < 32 || h < 32) return `The image is ${w}×${h}px; use at least 32×32px so logo matching is reliable.`;
    if (w > 4096 || h > 4096) return `The image is ${w}×${h}px; the maximum is 4096×4096px.`;
  } catch {
    return "This file couldn’t be read as an image.";
  }
  return null;
}

export function LogoField({ brand, pending, onPending, onChange }: { brand?: Brand; pending?: File | null; onPending?: (f: File | null) => void; onChange?: (b: Brand) => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bust, setBust] = useState(0);
  const preview = useMemo(() => (pending ? URL.createObjectURL(pending) : null), [pending]);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);

  const choose = async (file: File) => {
    setError(null);
    const problem = await checkLogoFile(file);
    if (problem) return setError(problem);
    if (!brand) return onPending?.(file); // new brand: uploaded right after the profile is created
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      const b = await api<Brand>(`/brands/${brand.id}/logo`, { method: "POST", body: fd });
      onChange?.(b);
      setBust(Date.now());
      toast({ tone: "success", title: "Logo saved", description: "Perceptual hashes computed for logo matching." });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const src = preview ?? (brand?.has_logo ? `/api/brands/${brand.id}/logo?v=${bust || brand.logo_phash}` : null);
  return (
    <div className="flex flex-wrap items-start gap-4">
      <div className="grid size-20 shrink-0 place-items-center overflow-hidden rounded-lg border border-ink-150 bg-white">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {src ? <img src={src} alt="Brand logo" className="size-full object-contain" /> : <ImageUp className="size-6 text-ink-300" aria-hidden />}
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" loading={busy} onClick={() => input.current?.click()}>{src ? "Replace logo" : "Choose logo"}</Button>
          {(pending || brand?.has_logo) && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={async () => {
                if (pending) return onPending?.(null);
                if (brand) onChange?.(await api<Brand>(`/brands/${brand.id}/logo`, { method: "DELETE" }));
              }}
            >
              Remove
            </Button>
          )}
        </div>
        <p className="text-[11.5px] text-ink-500">PNG, JPEG, WebP or GIF · up to 2 MB · 32–4096 px. Re-encoded on the server; SVG is not accepted.</p>
        {pending && <p className="text-[11.5px] text-teal-700">Will be uploaded when you create the brand.</p>}
        {brand?.logo_phash && !pending && <p className="font-mono text-[11px] text-ink-400">pHash {brand.logo_phash} · dHash {brand.logo_dhash}</p>}
        {error && <p role="alert" className="text-[12px] text-crit">{error}</p>}
        <input ref={input} type="file" accept={LOGO_TYPES.join(",")} className="hidden" aria-label="Logo file" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) choose(f); }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- form

const SECTIONS = [
  { id: "identity", label: "Name & aliases" },
  { id: "logo", label: "Logo" },
  { id: "web", label: "Website & domains" },
  { id: "social", label: "Social accounts" },
  { id: "apps", label: "Mobile apps" },
  { id: "products", label: "Products & identifiers" },
];

function Section({ id, title, description, children, actions }: { id: string; title: string; description: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <Card id={`section-${id}`} className="scroll-mt-20">
      <CardHeader title={title} description={description} actions={actions} />
      {children}
    </Card>
  );
}

function RowError({ msg }: { msg?: string }) {
  return msg ? <p role="alert" className="text-[11.5px] text-crit">{msg}</p> : null;
}

export function BrandForm({
  initial,
  onSubmit,
  submitLabel,
  brand,
  onBrandChange,
  pendingLogo,
  onPendingLogo,
}: {
  initial: BrandPayload;
  onSubmit: (p: CleanBrandPayload) => Promise<void>;
  submitLabel: string;
  brand?: Brand;
  onBrandChange?: (b: Brand) => void;
  pendingLogo?: File | null;
  onPendingLogo?: (f: File | null) => void;
}) {
  const [p, setP] = useState<BrandPayload>(initial);
  const [baseline, setBaseline] = useState<BrandPayload>(initial);
  const [errors, setErrors] = useState<{ fields: Record<string, string>; general: string[] }>({ fields: {}, general: [] });
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const dirty = JSON.stringify(p) !== JSON.stringify(baseline) || !!pendingLogo;
  const set = <K extends keyof BrandPayload>(k: K, v: BrandPayload[K]) => setP((x) => ({ ...x, [k]: v }));
  const setAcct = (i: number, patch: Partial<OfficialAccount>) => set("official_accounts", p.official_accounts.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const setApp = (i: number, patch: Partial<OfficialApp>) => set("official_apps", p.official_apps.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const fe = errors.fields;
  const errorCount = Object.keys(fe).length + errors.general.length;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({ fields: {}, general: [] });
    if (!p.name.trim() || p.name.trim().length < 2) {
      setErrors({ fields: { name: "Enter the brand name (at least 2 characters)." }, general: [] });
      document.getElementById("name")?.focus();
      return;
    }
    setSaving(true);
    try {
      await onSubmit(clean(p));
      setBaseline(p);
      setSavedAt(new Date().toISOString());
    } catch (err) {
      const mapped = err instanceof ApiError ? mapErrors(err, p) : { fields: {}, general: [(err as Error).message] };
      setErrors(mapped);
      requestAnimationFrame(() => document.querySelector<HTMLElement>("[aria-invalid=true], [data-form-errors]")?.focus());
    } finally {
      setSaving(false);
    }
  };

  const sectionErrors = (prefix: string[]) => Object.keys(fe).some((k) => prefix.some((x) => k === x || k.startsWith(x + ".")));
  const navErr: Record<string, boolean> = {
    identity: sectionErrors(["name", "aliases"]),
    web: sectionErrors(["website_url", "official_domains"]),
    social: sectionErrors(["official_accounts"]),
    apps: sectionErrors(["official_apps"]),
    products: sectionErrors(["keywords", "additional_identifiers", "description"]),
  };

  return (
    <form onSubmit={submit} noValidate className="grid gap-6 lg:grid-cols-[180px_minmax(0,1fr)]">
      <nav aria-label="Form sections" className="hidden lg:block">
        <ol className="sticky top-20 space-y-0.5 text-[12.5px]">
          {SECTIONS.map((s, i) => (
            <li key={s.id}>
              <a href={`#section-${s.id}`} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-ink-600 hover:bg-ink-100 hover:text-ink-900">
                <span className="tabular w-4 font-mono text-[11px] text-ink-400">{i + 1}</span>
                <span className="flex-1">{s.label}</span>
                {navErr[s.id] && <AlertTriangle className="size-3.5 text-crit" aria-label="Has errors" />}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="min-w-0 space-y-4">
        {errors.general.length > 0 && (
          <div role="alert" tabIndex={-1} data-form-errors className="rounded-md border border-[#efcdc4] bg-crit-bg px-3.5 py-2.5 text-[12.5px] text-crit outline-none">
            {errors.general.map((g) => <div key={g}>{g}</div>)}
          </div>
        )}

        <Section id="identity" title="Name & aliases" description="The names the detector compares candidates against. Only the brand name is required.">
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <Field label="Brand name" htmlFor="name" error={fe.name}>
              <Input id="name" required minLength={2} maxLength={120} value={p.name} aria-invalid={!!fe.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Acme Wallet" />
            </Field>
            <Field label="Aliases" htmlFor="aliases" hint="Abbreviations, former names, common misspellings. Each becomes a bounded search term." error={fe.aliases} optional>
              <TagInput id="aliases" value={p.aliases} onChange={(v) => set("aliases", v)} placeholder="Type and press Enter" max={20} />
            </Field>
          </div>
        </Section>

        <Section id="logo" title="Official logo" description="Compared with candidate avatars and app icons using perceptual hashes (pHash + dHash).">
          <div className="p-4">
            <LogoField brand={brand} pending={pendingLogo} onPending={onPendingLogo} onChange={onBrandChange} />
          </div>
        </Section>

        <Section id="web" title="Website & domains" description="Exact identifiers. Links to these domains are treated as official, and Bluesky handles on them are excluded.">
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <Field label="Official website" htmlFor="website" hint="Its domain is added to the official domains automatically." error={fe.website_url} optional>
              <Input id="website" type="url" inputMode="url" placeholder="https://www.example.com" value={p.website_url} aria-invalid={!!fe.website_url} onChange={(e) => set("website_url", e.target.value)} />
            </Field>
            <Field label="Other official domains" htmlFor="domains" hint="Subdomains are covered automatically." error={fe.official_domains} optional>
              <TagInput id="domains" value={p.official_domains} onChange={(v) => set("official_domains", v)} placeholder="example.com" />
            </Field>
          </div>
        </Section>

        <Section
          id="social"
          title="Official social accounts"
          description="Exact identifiers used to exclude your own accounts before scoring. Bluesky and Mastodon are scanned; other platforms are kept for reference."
          actions={<Button type="button" size="sm" icon={<Plus className="size-3.5" />} onClick={() => set("official_accounts", [...p.official_accounts, { platform: "bluesky", handle: "", profile_url: "", external_id: "" }])}>Add account</Button>}
        >
          <div className="divide-y divide-ink-150">
            {p.official_accounts.length === 0 && <p className="px-4 py-4 text-[12.5px] text-ink-500">No official accounts yet. Without them, your own accounts can appear as findings.</p>}
            {p.official_accounts.map((a, i) => {
              const k = (f: string) => fe[`official_accounts.${i}.${f}`];
              return (
                <fieldset key={i} className="grid items-start gap-2 px-4 py-3 md:grid-cols-[140px_1fr_1.3fr_1fr_auto]">
                  <legend className="sr-only">Official account {i + 1}</legend>
                  <Field label="Platform" htmlFor={`pf${i}`} hint={SCANNED.has(a.platform) ? undefined : "Not scanned"}>
                    <Select id={`pf${i}`} value={a.platform} onChange={(e) => setAcct(i, { platform: e.target.value })}>
                      {PLATFORMS.map((x) => <option key={x} value={x}>{x}</option>)}
                    </Select>
                  </Field>
                  <Field label="Handle" htmlFor={`h${i}`} error={k("handle")}>
                    <Input id={`h${i}`} value={a.handle} aria-invalid={!!k("handle")} placeholder="acme.com or acme@mastodon.social" onChange={(e) => setAcct(i, { handle: e.target.value })} />
                  </Field>
                  <Field label="Profile URL" htmlFor={`u${i}`} error={k("profile_url")} optional>
                    <Input id={`u${i}`} type="url" value={a.profile_url ?? ""} aria-invalid={!!k("profile_url")} placeholder="https://…" onChange={(e) => setAcct(i, { profile_url: e.target.value })} />
                  </Field>
                  <Field label="Account ID" htmlFor={`x${i}`} error={k("external_id")} optional>
                    <Input id={`x${i}`} value={a.external_id ?? ""} placeholder="did:plc:…" onChange={(e) => setAcct(i, { external_id: e.target.value })} />
                  </Field>
                  <Button type="button" variant="ghost" className="mt-6" aria-label={`Remove official account ${i + 1}`} onClick={() => set("official_accounts", p.official_accounts.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></Button>
                  <div className="md:col-span-5"><RowError msg={k("platform")} /></div>
                </fieldset>
              );
            })}
          </div>
        </Section>

        <Section
          id="apps"
          title="Official mobile apps"
          description="Excluded by bundle/package ID or Apple track ID. Publisher IDs identify your developer accounts; a matching developer name alone is never trusted."
          actions={<Button type="button" size="sm" icon={<Plus className="size-3.5" />} onClick={() => set("official_apps", [...p.official_apps, { store: "apple", name: "", app_id: "", track_id: "", publisher_id: "", publisher_name: "", url: "" }])}>Add app</Button>}
        >
          <div className="divide-y divide-ink-150">
            {p.official_apps.length === 0 && <p className="px-4 py-4 text-[12.5px] text-ink-500">No official apps yet. Add them so your own listings are never reported.</p>}
            {p.official_apps.map((a, i) => {
              const k = (f: string) => fe[`official_apps.${i}.${f}`];
              return (
                <fieldset key={i} className="grid items-start gap-2 px-4 py-3 md:grid-cols-6">
                  <legend className="sr-only">Official app {i + 1}</legend>
                  <Field label="Store" htmlFor={`st${i}`} error={k("store")}>
                    <Select id={`st${i}`} value={a.store} onChange={(e) => setApp(i, { store: e.target.value })}>
                      <option value="apple">App Store</option>
                      <option value="google_play">Google Play</option>
                    </Select>
                  </Field>
                  <div className="md:col-span-2">
                    <Field label="App name" htmlFor={`an${i}`} error={k("name")} optional>
                      <Input id={`an${i}`} value={a.name ?? ""} placeholder="As shown in the store" onChange={(e) => setApp(i, { name: e.target.value })} />
                    </Field>
                  </div>
                  <div className="md:col-span-2">
                    <Field label="Bundle / package ID" htmlFor={`ai${i}`} error={k("app_id")}>
                      <Input id={`ai${i}`} value={a.app_id} aria-invalid={!!k("app_id")} placeholder="com.acme.wallet" onChange={(e) => setApp(i, { app_id: e.target.value })} />
                    </Field>
                  </div>
                  <div className="flex items-start justify-end">
                    <Button type="button" variant="ghost" className="mt-6" aria-label={`Remove official app ${i + 1}`} onClick={() => set("official_apps", p.official_apps.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></Button>
                  </div>
                  <Field label="Track ID" htmlFor={`ti${i}`} error={k("track_id")} optional>
                    <Input id={`ti${i}`} value={a.track_id ?? ""} disabled={a.store !== "apple"} aria-invalid={!!k("track_id")} placeholder={a.store === "apple" ? "id123456" : "Apple only"} onChange={(e) => setApp(i, { track_id: e.target.value })} />
                  </Field>
                  <Field label="Publisher ID" htmlFor={`pi${i}`} error={k("publisher_id")} optional>
                    <Input id={`pi${i}`} value={a.publisher_id ?? ""} placeholder={a.store === "apple" ? "artistId" : "developer id"} onChange={(e) => setApp(i, { publisher_id: e.target.value })} />
                  </Field>
                  <div className="md:col-span-2">
                    <Field label="Publisher name" htmlFor={`pn${i}`} error={k("publisher_name")} optional>
                      <Input id={`pn${i}`} value={a.publisher_name ?? ""} onChange={(e) => setApp(i, { publisher_name: e.target.value })} />
                    </Field>
                  </div>
                  <div className="md:col-span-2">
                    <Field label="Listing URL" htmlFor={`lu${i}`} error={k("url")} optional>
                      <Input id={`lu${i}`} type="url" value={a.url ?? ""} aria-invalid={!!k("url")} placeholder="https://apps.apple.com/…" onChange={(e) => setApp(i, { url: e.target.value })} />
                    </Field>
                  </div>
                </fieldset>
              );
            })}
          </div>
        </Section>

        <Section id="products" title="Products & identifiers" description="Similarity references only — used to score candidates, never to exclude them.">
          <div className="grid gap-4 p-4 md:grid-cols-2">
            <Field label="Product names & keywords" htmlFor="kw" error={fe.keywords} optional>
              <TagInput id="kw" value={p.keywords} onChange={(v) => set("keywords", v)} placeholder="Product names, taglines" />
            </Field>
            <Field label="Additional identifiers" htmlFor="ids" hint="Legal entity names, trademark or registration numbers." error={fe.additional_identifiers} optional>
              <TagInput id="ids" value={p.additional_identifiers} onChange={(v) => set("additional_identifiers", v)} placeholder="Acme Payments Ltd" max={30} />
            </Field>
            <div className="md:col-span-2">
              <Field label="Description" htmlFor="desc" hint="Paste your official store or profile description — copied text in look-alikes is a strong signal." error={fe.description} optional>
                <Textarea id="desc" value={p.description} maxLength={4000} onChange={(e) => set("description", e.target.value)} />
              </Field>
            </div>
          </div>
        </Section>


        {/* Save bar */}
        <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-150 bg-paper/95 px-4 py-2.5 shadow-pop backdrop-blur">
          <span className="text-[12.5px]" aria-live="polite">
            {errorCount > 0 ? (
              <span className="inline-flex items-center gap-1.5 text-crit"><AlertTriangle className="size-3.5" /> {errorCount} issue{errorCount > 1 ? "s" : ""} to fix before saving</span>
            ) : dirty ? (
              <span className="inline-flex items-center gap-1.5 text-med"><span className="size-1.5 rounded-full bg-med" /> Unsaved changes</span>
            ) : savedAt ? (
              <span className="inline-flex items-center gap-1.5 text-forest-600"><Check className="size-3.5" /> Saved {relTime(savedAt)}</span>
            ) : (
              <span className="text-ink-500">No changes</span>
            )}
          </span>
          <div className="flex gap-2">
            {dirty && <Button type="button" variant="ghost" onClick={() => { setP(baseline); setErrors({ fields: {}, general: [] }); onPendingLogo?.(null); }}>Discard</Button>}
            <Button type="submit" variant="primary" loading={saving} disabled={saving || (!dirty && !!brand)}>{submitLabel}</Button>
          </div>
        </div>
      </div>
    </form>
  );
}

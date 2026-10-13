export const SOURCE_LABELS: Record<string, string> = {
  bluesky: "Bluesky",
  mastodon: "Mastodon",
  apple_app_store: "App Store",
  apple: "App Store",
  google_play: "Google Play",
  youtube: "YouTube",
  ct_domains: "Domains (CT logs)",
  domain: "Web domain",
  demo: "Synthetic demo",
  import: "CSV import",
  x: "X",
  instagram: "Instagram",
};

export const GROUP_LABELS: Record<string, string> = {
  identity: "Name / handle",
  visual: "Logo",
  content: "Description",
  links: "Links",
  behavior: "Scam indicators",
  provenance: "Publisher",
};

export const SIGNAL_LABELS: Record<string, string> = {
  name: "Display name",
  handle: "Handle",
  package: "Bundle / package ID",
  logo: "Logo / avatar",
  description: "Description text",
  urls: "External links",
  scam: "Scam indicators",
  publisher: "Publisher",
};

export function sourceLabel(s: string | null | undefined): string {
  if (!s) return "—";
  return SOURCE_LABELS[s] ?? s.replace(/_/g, " ");
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  const diff = (Date.now() - d) / 1000;
  const abs = Math.abs(diff);
  const fmt = (n: number, u: string) => `${Math.round(n)} ${u}${Math.round(n) === 1 ? "" : "s"}`;
  let out: string;
  if (abs < 45) out = "just now";
  else if (abs < 3600) out = fmt(abs / 60, "min");
  else if (abs < 86400) out = fmt(abs / 3600, "hour");
  else if (abs < 86400 * 30) out = fmt(abs / 86400, "day");
  else return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  if (out === "just now") return out;
  return diff >= 0 ? `${out} ago` : `in ${out}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

/** Map backend avatar references to displayable URLs. demo-asset:// images are served by the API. */
export function avatarSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("demo-asset://")) return `/api/demo/assets/${encodeURIComponent(url.slice("demo-asset://".length))}`;
  if (url.startsWith("https://")) return url;
  return null;
}

export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return /^https?:\/\//i.test(url) ? url : undefined;
}

export function plural(n: number, word: string, pluralWord?: string) {
  return `${n.toLocaleString()} ${n === 1 ? word : pluralWord ?? word + "s"}`;
}

export const DETECTION_TYPE_LABELS: Record<string, string> = {
  fake_brand_page: "Fake brand page",
  fake_profile: "Fake profile",
  scam_account: "Scam account",
  lookalike_account: "Look-alike account",
  suspicious_app: "Suspicious app",
  lookalike_app: "Look-alike app",
  official_publisher_app: "Official publisher app",
  phishing_domain: "Possible phishing domain",
  lookalike_domain: "Look-alike domain",
  unrelated: "Unrelated",
};

/** Per-query outcomes recorded by the scanner. */
export const OUTCOME_LABELS: Record<string, string> = {
  ok: "Successful",
  empty: "No results",
  rate_limited: "Rate limited",
  timeout: "Timed out",
  unavailable: "Unavailable",
  auth_required: "Access denied / auth required",
  error: "Error",
};

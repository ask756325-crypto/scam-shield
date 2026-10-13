"use client";

import { Bell, Send, Webhook } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, Checkbox, ErrorState, Field, Input, Notice, Select, Skeleton } from "../ui";

interface Prefs { email_new_critical: boolean; email_new_high: boolean; email_source_failure: boolean; digest: "off" | "daily"; digest_hour: number; timezone: string; last_digest_at: string | null; email_delivery: "email" | "server_log" | "unavailable"; email: string }
interface Hook { configured: boolean; url_masked: string | null; enabled: boolean; events: string[]; available_events: string[] }
interface LogRow { id: number; channel: string; event: string; recipient: string; subject: string; status: string; detail: string; scan_id: number | null; created_at: string }

const EVENT_LABEL: Record<string, string> = { new_threat: "New high-risk finding", source_failure: "Source failing", schedule_paused: "Schedule paused", digest: "Daily digest", test: "Test" };
const STATUS_TONE: Record<string, "forest" | "med" | "crit" | "outline"> = { sent: "forest", logged: "med", skipped: "outline", failed: "crit" };

function zones(): string[] {
  try {
    const z = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone");
    if (z?.length) return z.includes("UTC") ? z : ["UTC", ...z];
  } catch {
    /* older browsers */
  }
  return ["UTC"];
}

export function NotificationsTab({ owner }: { owner: boolean }) {
  const toast = useToast();
  const { data: prefs, error, setData: setPrefs } = useApi<Prefs>("/notifications/preferences");
  const { data: hook, setData: setHook } = useApi<Hook>("/notifications/webhook");
  const { data: log, reload: reloadLog } = useApi<LogRow[]>("/notifications/log", { limit: 30 });
  const [draft, setDraft] = useState<Prefs | null>(null);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [urlErr, setUrlErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const allZones = useMemo(zones, []);
  useEffect(() => prefs && setDraft(prefs), [prefs]);
  useEffect(() => hook && setEvents(hook.events), [hook]);
  if (error) return <ErrorState error={error} />;
  if (!draft || !hook) return <Skeleton className="h-64" />;

  const savePrefs = async () => {
    setBusy("prefs");
    try {
      const { email_delivery: _d, email: _e, last_digest_at: _l, ...body } = draft; // eslint-disable-line @typescript-eslint/no-unused-vars
      setPrefs(await api<Prefs>("/notifications/preferences", { method: "PUT", body }));
      toast({ tone: "success", title: "Notification preferences saved" });
    } catch (e) {
      toast({ tone: "error", title: "Not saved", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const saveHook = async (patch: Partial<{ url: string; enabled: boolean; clear: boolean }>) => {
    setBusy("hook");
    setUrlErr(null);
    try {
      setHook(await api<Hook>("/notifications/webhook", { method: "PUT", body: { enabled: hook.enabled, events, ...patch } }));
      setUrl("");
      toast({ tone: "success", title: patch.clear ? "Webhook removed" : "Webhook saved" });
    } catch (e) {
      const d = e instanceof ApiError ? (e.data as { detail?: { message?: string } })?.detail : undefined;
      setUrlErr(d?.message ?? (e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const test = async (channel: "email" | "webhook") => {
    setBusy(`test-${channel}`);
    try {
      const r = await api<{ status: string; detail: string }>(`/notifications/test`, { method: "POST", query: { channel } });
      toast({ tone: r.status === "sent" ? "success" : r.status === "failed" ? "error" : "info", title: `Test ${channel}: ${r.status}`, description: r.detail });
      reloadLog(true);
    } catch (e) {
      toast({ tone: "error", title: "Test not sent", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(prefs);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><Bell className="size-4 text-ink-500" /> Email alerts for you</span>}
          description={`Sent to ${draft.email}. Alerts fire after a scan: when a finding first appears at, or rises to, high or critical, or when a source fails twice in a row.`}
          actions={<Button size="sm" variant="ghost" icon={<Send className="size-3.5" />} loading={busy === "test-email"} onClick={() => test("email")}>Send test</Button>} />
        {draft.email_delivery !== "email" && (
          <div className="px-4 pt-3">
            <Notice tone="warn">
              {draft.email_delivery === "server_log"
                ? "No SMTP server is configured. In development, alert emails are written to the backend log instead of being sent."
                : "No SMTP server is configured, so alert emails cannot be delivered. Ask an administrator to set SCAMSHIELD_SMTP_*."}
            </Notice>
          </div>
        )}
        <div className="grid gap-3 p-4 sm:grid-cols-2">
          <Checkbox checked={draft.email_new_critical} onChange={(v) => setDraft({ ...draft, email_new_critical: v })} label="New critical findings" description="Corroborated impersonation with scam indicators" />
          <Checkbox checked={draft.email_new_high} onChange={(v) => setDraft({ ...draft, email_new_high: v })} label="New high findings" description="More frequent; useful for small brands" />
          <Checkbox checked={draft.email_source_failure} onChange={(v) => setDraft({ ...draft, email_source_failure: v })} label="Source failures and paused schedules" description="A source failed in two consecutive scans, or a schedule paused itself" />
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Daily digest" htmlFor="dg">
              <Select id="dg" className="w-28" value={draft.digest} onChange={(e) => setDraft({ ...draft, digest: e.target.value as "off" | "daily" })}>
                <option value="off">Off</option>
                <option value="daily">Daily</option>
              </Select>
            </Field>
            {draft.digest === "daily" && (
              <>
                <Field label="At" htmlFor="dh">
                  <Select id="dh" className="w-24" value={draft.digest_hour} onChange={(e) => setDraft({ ...draft, digest_hour: Number(e.target.value) })}>
                    {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                  </Select>
                </Field>
                <Field label="Time zone" htmlFor="dtz">
                  <Select id="dtz" className="w-52" value={draft.timezone} onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}>
                    {allZones.map((z) => <option key={z} value={z}>{z}</option>)}
                  </Select>
                </Field>
              </>
            )}
          </div>
        </div>
        {draft.last_digest_at && <p className="px-4 pb-2 text-[11.5px] text-ink-500">Last digest {relTime(draft.last_digest_at)}</p>}
        <div className="flex justify-end border-t border-ink-150 px-4 py-3">
          <Button variant="primary" disabled={!dirty} loading={busy === "prefs"} onClick={savePrefs}>Save preferences</Button>
        </div>
      </Card>

      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><Webhook className="size-4 text-ink-500" /> Team webhook</span>}
          description="Posts alerts as JSON with a Slack-compatible “text” field. The URL is stored on the server as a secret and only shown masked."
          actions={hook.configured && <Button size="sm" variant="ghost" icon={<Send className="size-3.5" />} loading={busy === "test-webhook"} onClick={() => test("webhook")}>Send test</Button>} />
        <div className="space-y-3 p-4">
          {hook.configured ? (
            <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <Badge tone={hook.enabled ? "forest" : "outline"} dot>{hook.enabled ? "Enabled" : "Disabled"}</Badge>
              <code className="font-mono text-[11.5px] text-ink-700">{hook.url_masked}</code>
            </div>
          ) : <p className="text-[12.5px] text-ink-500">No webhook configured.</p>}
          {owner ? (
            <>
              <Field label={hook.configured ? "Replace URL" : "Webhook URL"} htmlFor="wh" error={urlErr} hint="https only; must resolve to a public address.">
                <Input id="wh" type="url" placeholder="https://hooks.slack.com/services/…" value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off" />
              </Field>
              <div role="group" aria-label="Webhook events" className="flex flex-wrap gap-x-5 gap-y-2">
                {hook.available_events.map((ev) => (
                  <Checkbox key={ev} label={EVENT_LABEL[ev] ?? ev} checked={events.includes(ev)} onChange={(v) => setEvents(v ? [...events, ev] : events.filter((x) => x !== ev))} />
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" loading={busy === "hook"} disabled={!url && !hook.configured} onClick={() => saveHook({ ...(url ? { url } : {}), enabled: true })}>{hook.enabled ? "Save" : "Save and enable"}</Button>
                {hook.configured && hook.enabled && <Button variant="ghost" disabled={busy === "hook"} onClick={() => saveHook({ enabled: false })}>Disable</Button>}
                {hook.configured && <Button variant="ghost" disabled={busy === "hook"} onClick={() => saveHook({ clear: true, enabled: false })}>Remove</Button>}
              </div>
            </>
          ) : <p className="text-[11.5px] text-ink-500">Only organization owners can change the webhook.</p>}
        </div>
      </Card>

      <Card>
        <CardHeader title="Delivery log" description="Every alert attempt with its real outcome: sent, logged (development, no SMTP), skipped (no SMTP) or failed." />
        {!log ? <div className="p-4"><Skeleton className="h-16" /></div> : log.length === 0 ? <p className="px-4 py-3 text-[12.5px] text-ink-500">No notifications yet.</p> : (
          <ul className="divide-y divide-ink-150">
            {log.map((r) => (
              <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-2 text-[12px]">
                <Badge tone={STATUS_TONE[r.status] ?? "outline"}>{r.status}</Badge>
                <span className="text-ink-500">{r.channel}</span>
                <span className="font-medium text-ink-900">{EVENT_LABEL[r.event] ?? r.event}</span>
                <span className="min-w-0 flex-1 truncate text-ink-700" title={r.subject}>{r.subject}</span>
                <span className="text-ink-400" title={dateTime(r.created_at)}>{relTime(r.created_at)}</span>
                <span className="basis-full pl-1 text-[11.5px] text-ink-500">{r.recipient} · {r.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

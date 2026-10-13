"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorState, Field, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";

function AcceptForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const { data, error, loading } = useApi<{ email: string; organization: string; role: string }>(token ? `/auth/invite/${encodeURIComponent(token)}` : null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);

  if (!token || error)
    return (
      <>
        <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink-950">Invitation unavailable</h1>
        <p className="mt-2 text-[13px] text-ink-500">This invitation link is invalid, expired or already used. Ask an owner of your organization to send a new one.</p>
        <Link href="/signin" className="mt-6 inline-block text-[13px] font-medium text-teal-700 hover:underline">Back to sign in</Link>
      </>
    );
  if (loading || !data) return <Skeleton className="h-48" />;

  return (
    <>
      <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink-950">Join {data.organization}</h1>
      <p className="mt-1.5 text-[13px] text-ink-500">You were invited as <span className="font-medium capitalize text-ink-800">{data.role}</span>. Create your account to continue.</p>
      <form
        className="mt-7 space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr(null);
          try {
            await api("/auth/accept-invite", { method: "POST", body: { token, name, password } });
            router.replace("/app");
          } catch (e) {
            setErr(e as Error);
            setBusy(false);
          }
        }}
      >
        <Field label="Email" htmlFor="email"><Input id="email" value={data.email} disabled /></Field>
        <Field label="Your name" htmlFor="name"><Input id="name" required maxLength={120} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Password" htmlFor="pw" hint="At least 10 characters, mixing letters with numbers or symbols.">
          <Input id="pw" type="password" required minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {err && <ErrorState error={err} />}
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Create account</Button>
      </form>
    </>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptForm />
    </Suspense>
  );
}

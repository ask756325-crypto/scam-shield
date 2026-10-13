"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorState, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);

  if (!token)
    return (
      <>
        <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink-950">Link missing</h1>
        <p className="mt-2 text-[13px] text-ink-500">This page needs the link from your reset email.</p>
        <Link href="/forgot-password" className="mt-6 inline-block text-[13px] font-medium text-teal-700 hover:underline">Request a new link</Link>
      </>
    );

  return (
    <>
      <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink-950">Choose a new password</h1>
      <p className="mt-1.5 text-[13px] text-ink-500">All existing sessions will be signed out.</p>
      <form
        className="mt-7 space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (password !== confirm) {
            setError(new Error("Passwords do not match."));
            return;
          }
          setLoading(true);
          setError(null);
          try {
            await api("/auth/password-reset/confirm", { method: "POST", body: { token, password } });
            router.replace("/signin?reset=1");
          } catch (err) {
            setError(err as Error);
            setLoading(false);
          }
        }}
      >
        <Field label="New password" htmlFor="pw" hint="At least 10 characters, mixing letters with numbers or symbols.">
          <Input id="pw" type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        </Field>
        <Field label="Confirm password" htmlFor="pw2">
          <Input id="pw2" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        {error && <ErrorState error={error} />}
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
          Update password
        </Button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}

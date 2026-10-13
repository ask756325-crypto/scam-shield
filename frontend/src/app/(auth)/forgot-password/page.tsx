"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, ErrorState, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [delivery, setDelivery] = useState<string | null>(null);

  useEffect(() => {
    api<{ password_reset_delivery: string }>("/auth/config").then((c) => setDelivery(c.password_reset_delivery)).catch(() => {});
  }, []);

  return (
    <>
      <h1 className="text-[24px] font-semibold tracking-[-0.025em] text-ink-950">Reset your password</h1>
      <p className="mt-1.5 text-[13px] text-ink-500">Enter your account email and we’ll issue a single-use reset link valid for 30 minutes.</p>
      {delivery === "server_log" && (
        <Notice tone="warn" className="mt-5">
          Development mode: no email server is configured, so the reset link is written to the backend server log instead of being emailed.
        </Notice>
      )}
      {delivery === "unavailable" && (
        <Notice tone="warn" className="mt-5">
          Password reset email is not configured on this deployment. Contact your administrator.
        </Notice>
      )}
      {sent ? (
        <div className="mt-7 rounded-lg border border-ink-150 bg-paper p-5">
          <MailCheck className="size-5 text-forest-600" />
          <p className="mt-2 text-[13.5px] font-medium text-ink-900">Check your inbox</p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-500">
            If an account exists for {email}, a reset link has been issued. For security we don’t confirm whether an address is registered.
          </p>
        </div>
      ) : (
        <form
          className="mt-7 space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setLoading(true);
            setError(null);
            try {
              await api("/auth/password-reset/request", { method: "POST", body: { email } });
              setSent(true);
            } catch (err) {
              setError(err as Error);
            } finally {
              setLoading(false);
            }
          }}
        >
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </Field>
          {error && <ErrorState error={error} />}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
            Send reset link
          </Button>
        </form>
      )}
      <p className="mt-6 text-center text-[13px] text-ink-500">
        <Link href="/signin" className="font-medium text-teal-700 hover:underline">
          Back to sign in
        </Link>
      </p>
    </>
  );
}

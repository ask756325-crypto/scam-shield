"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { FieldError, PasswordChecklist, PasswordInput, passwordChecks } from "@/components/auth";
import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { safeNext } from "@/lib/redirect";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
type Key = "name" | "organization" | "email" | "password";

function SignUpForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [form, setForm] = useState({ name: "", organization: "", email: "", password: "" });
  const [touched, setTouched] = useState<Record<Key, boolean>>({ name: false, organization: false, email: false, password: false });
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const refs = { name: useRef<HTMLInputElement>(null), organization: useRef<HTMLInputElement>(null), email: useRef<HTMLInputElement>(null), password: useRef<HTMLInputElement>(null) };

  useEffect(() => {
    api("/auth/me").then(() => router.replace(next)).catch(() => {});
  }, [router, next]);

  const errors: Record<Key, string | null> = {
    name: !form.name.trim() ? "Enter your name." : null,
    organization: !form.organization.trim() ? "Enter your organization’s name." : null,
    email: !form.email ? "Enter your work email." : !EMAIL_RE.test(form.email) ? "Enter a valid email address, like name@company.com." : null,
    password: passwordChecks(form.password, form.email).every((c) => c.ok) ? null : "Choose a password that meets every requirement below.",
  };
  const show = (k: Key) => ((touched[k] || submitted) && errors[k]) || null;
  const bind = (k: Key) => ({
    id: k,
    ref: refs[k],
    value: form[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: k === "email" ? e.target.value.trim() : e.target.value }),
    onBlur: () => setTouched((t) => ({ ...t, [k]: true })),
    "aria-invalid": !!show(k),
    "aria-describedby": [show(k) ? `${k}-error` : "", k === "password" ? "password-policy" : ""].filter(Boolean).join(" ") || undefined,
  });

  return (
    <>
      <h1 className="text-[26px] font-semibold tracking-[-0.03em] text-ink-950">Create your workspace</h1>
      <p className="mt-1.5 text-[13.5px] text-ink-500">Your organization keeps brands, scans and decisions private to your team.</p>

      {error && (
        <div role="alert" className="mt-6 flex items-start gap-2.5 rounded-md border border-[#efcdc4] bg-crit-bg px-3.5 py-2.5 text-[12.5px] text-crit animate-fade-in">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            {error.status === 409 ? (
              <>
                An account already exists for <strong className="font-medium">{form.email}</strong>.{" "}
                <Link href={`/signin${next !== "/app" ? `?next=${encodeURIComponent(next)}` : ""}`} className="font-medium underline underline-offset-2">Sign in instead</Link>{" "}
                or <Link href="/forgot-password" className="font-medium underline underline-offset-2">reset the password</Link>.
              </>
            ) : error.status === 0 || error.status >= 500 ? (
              "We couldn’t reach the server, so no account was created. Please try again."
            ) : (
              error.message
            )}
          </span>
        </div>
      )}

      <form
        className="mt-6 space-y-4"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault();
          setSubmitted(true);
          setError(null);
          const first = (Object.keys(errors) as Key[]).find((k) => errors[k]);
          if (first) return refs[first].current?.focus();
          setLoading(true);
          try {
            await api("/auth/signup", { method: "POST", body: form });
            router.replace(next === "/app" ? "/app?welcome=1" : next);
          } catch (err) {
            setError(err instanceof ApiError ? err : new ApiError(0, "Network error"));
            setLoading(false);
          }
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Your name" htmlFor="name">
            <Input autoComplete="name" maxLength={120} autoFocus {...bind("name")} />
            <FieldError id="name-error" message={show("name")} />
          </Field>
          <Field label="Organization" htmlFor="organization">
            <Input autoComplete="organization" maxLength={120} {...bind("organization")} />
            <FieldError id="organization-error" message={show("organization")} />
          </Field>
        </div>
        <Field label="Work email" htmlFor="email" hint={!show("email") ? "We’ll send a link to verify this address." : undefined}>
          <Input type="email" inputMode="email" autoComplete="email" {...bind("email")} />
          <FieldError id="email-error" message={show("email")} />
        </Field>
        <div className="space-y-1.5">
          <label htmlFor="password" className="text-[12.5px] font-medium text-ink-800">Password</label>
          <PasswordInput autoComplete="new-password" maxLength={256} {...bind("password")} />
          <FieldError id="password-error" message={show("password")} />
          <PasswordChecklist id="password-policy" password={form.password} email={form.email} />
        </div>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading} disabled={loading}>
          {loading ? "Creating account…" : "Create account"}
        </Button>
        <p className="text-center text-[11.5px] leading-relaxed text-ink-500">
          By creating an account you agree to the <Link href="/terms" className="underline underline-offset-2">Terms</Link> and{" "}
          <Link href="/privacy" className="underline underline-offset-2">Privacy notice</Link>.
        </p>
      </form>
      <p className="mt-6 border-t border-ink-150 pt-5 text-center text-[13px] text-ink-500">
        Already have an account?{" "}
        <Link href="/signin" className="font-medium text-teal-700 hover:underline">Sign in</Link>
      </p>
    </>
  );
}

export default function SignUpPage() {
  return (
    <Suspense>
      <SignUpForm />
    </Suspense>
  );
}

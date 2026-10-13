"use client";

import { AlertTriangle, CheckCircle2, Clock, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { FieldError, PasswordInput } from "@/components/auth";
import { Button, Checkbox, Field, Input, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { safeNext } from "@/lib/redirect";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Second step of sign-in when the account has two-factor authentication on. */
function SecondFactor({ challenge, onDone, onRestart }: { challenge: string; onDone: () => void; onRestart: () => void }) {
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!code.trim()) return setError(useRecovery ? "Enter one of your recovery codes." : "Enter the 6-digit code from your authenticator app.");
    setLoading(true);
    try {
      await api("/auth/login/2fa", { method: "POST", body: useRecovery ? { challenge, recovery_code: code } : { challenge, code } });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
      setCode("");
    }
  };
  return (
    <>
      <h1 className="inline-flex items-center gap-2 text-[26px] font-semibold tracking-[-0.03em] text-ink-950"><ShieldCheck className="size-6 text-forest-600" /> Two-factor check</h1>
      <p className="mt-1.5 text-[13.5px] text-ink-500">{useRecovery ? "Enter one of the recovery codes you saved when you turned on two-factor authentication. Each code works once." : "Enter the 6-digit code from your authenticator app."}</p>
      {error && (
        <div role="alert" className="mt-5 flex items-start gap-2.5 rounded-md border border-[#efcdc4] bg-crit-bg px-3.5 py-2.5 text-[12.5px] text-crit">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      <form className="mt-6 space-y-4" onSubmit={submit} noValidate>
        <Field label={useRecovery ? "Recovery code" : "Authentication code"} htmlFor="otp">
          <Input id="otp" autoFocus autoComplete="one-time-code" inputMode={useRecovery ? "text" : "numeric"} maxLength={useRecovery ? 20 : 6}
            placeholder={useRecovery ? "XXXXX-XXXXX" : "123456"} value={code}
            onChange={(e) => setCode(useRecovery ? e.target.value.toUpperCase() : e.target.value.replace(/\D/g, ""))} />
        </Field>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading} disabled={loading}>Verify and sign in</Button>
      </form>
      <div className="mt-5 flex justify-between text-[12.5px]">
        <button type="button" className="text-teal-700 hover:underline" onClick={() => { setUseRecovery((v) => !v); setCode(""); setError(null); }}>
          {useRecovery ? "Use authenticator code" : "Use a recovery code"}
        </button>
        <button type="button" className="text-ink-500 hover:underline" onClick={onRestart}>Start over</button>
      </div>
    </>
  );
}

function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const reason = params.get("reason");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [rememberDays, setRememberDays] = useState(30);
  const [challenge, setChallenge] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  // Already signed in (valid server session)? Go straight to the destination. A 401 here is expected and silent.
  useEffect(() => {
    api("/auth/me").then(() => router.replace(next)).catch(() => {});
    api<{ remember_me_days: number }>("/auth/config").then((c) => setRememberDays(c.remember_me_days)).catch(() => {});
  }, [router, next]);

  const emailError = !email ? "Enter your email address." : !EMAIL_RE.test(email) ? "Enter a valid email address, like name@company.com." : null;
  const passwordError = !password ? "Enter your password." : null;
  const showEmailErr = (touched.email || submitted) && emailError;
  const showPwErr = (touched.password || submitted) && passwordError;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    if (emailError) return emailRef.current?.focus();
    if (passwordError) return passwordRef.current?.focus();
    setLoading(true);
    try {
      const r = await api<{ two_factor_required?: boolean; challenge?: string }>("/auth/login", { method: "POST", body: { email, password, remember } });
      if (r.two_factor_required && r.challenge) {
        setChallenge(r.challenge);
        setPassword("");
        setLoading(false);
        return;
      }
      router.replace(next);
    } catch (err) {
      setError(err as Error);
      setLoading(false);
      // Clear the password for a fresh attempt without immediately re-flagging the now-empty field.
      setPassword("");
      setSubmitted(false);
      setTouched({ email: true, password: false });
      passwordRef.current?.focus();
    }
  };

  const status = (error as ApiError | null)?.status;

  if (challenge) return <SecondFactor challenge={challenge} onDone={() => router.replace(next)} onRestart={() => { setChallenge(null); setError(null); }} />;

  return (
    <>
      <h1 className="text-[26px] font-semibold tracking-[-0.03em] text-ink-950">Sign in</h1>
      <p className="mt-1.5 text-[13.5px] text-ink-500">Continue monitoring your brands.</p>

      <div className="mt-6 space-y-3 empty:hidden">
        {reason === "expired" && (
          <Notice tone="warn" icon={<Clock className="size-4" />}>Your session expired. Sign in again to continue where you left off.</Notice>
        )}
        {params.get("reset") === "1" && (
          <Notice tone="teal" icon={<CheckCircle2 className="size-4" />}>Password updated. Sign in with your new password.</Notice>
        )}
        {params.get("signedout") === "1" && <Notice tone="neutral">You’ve been signed out.</Notice>}
        {error && (
          <div role="alert" className="flex items-start gap-2.5 rounded-md border border-[#efcdc4] bg-crit-bg px-3.5 py-2.5 text-[12.5px] text-crit animate-fade-in">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>
              {status === 401 ? "That email and password don’t match an account. Check both and try again." : error.message}
              {status === 401 && (
                <>
                  {" "}
                  <Link href="/forgot-password" className="font-medium underline underline-offset-2">Reset your password</Link>
                </>
              )}
            </span>
          </div>
        )}
      </div>

      <form className="mt-6 space-y-4" onSubmit={submit} noValidate>
        <Field label="Work email" htmlFor="email">
          <Input
            ref={emailRef}
            id="email"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value.trim())}
            onBlur={() => setTouched((t) => ({ ...t, email: true }))}
            aria-invalid={!!showEmailErr}
            aria-describedby={showEmailErr ? "email-error" : undefined}
          />
          <FieldError id="email-error" message={showEmailErr ? emailError : null} />
        </Field>
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between">
            <label htmlFor="password" className="text-[12.5px] font-medium text-ink-800">Password</label>
            <Link href="/forgot-password" className="text-[12px] text-teal-700 hover:underline">Forgot password?</Link>
          </div>
          <PasswordInput
            ref={passwordRef}
            id="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, password: true }))}
            aria-invalid={!!showPwErr}
            aria-describedby={showPwErr ? "password-error" : undefined}
          />
          <FieldError id="password-error" message={showPwErr ? passwordError : null} />
        </div>
        <Checkbox
          checked={remember}
          onChange={setRemember}
          label="Keep me signed in"
          description={remember ? `Stays signed in on this device for ${rememberDays} days.` : "Otherwise you’re signed out when the browser closes (or after 12 hours)."}
        />
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading} disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-7 border-t border-ink-150 pt-5 text-center text-[13px] text-ink-500">
        New to ScamShield?{" "}
        <Link href={next !== "/app" ? `/signup?next=${encodeURIComponent(next)}` : "/signup"} className="font-medium text-teal-700 hover:underline">
          Create an account
        </Link>
      </p>
    </>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}

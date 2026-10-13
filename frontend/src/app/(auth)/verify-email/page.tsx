"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<{ status: "loading" | "ok" | "error"; message?: string }>({ status: token ? "loading" : "error", message: "This page needs the link from your verification email." });
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true; // tokens are single-use; don't double-submit under React strict mode
    api<{ email: string }>("/auth/verify-email", { method: "POST", body: { token } })
      .then((r) => setState({ status: "ok", message: r.email }))
      .catch((e) => setState({ status: "error", message: (e as Error).message }));
  }, [token]);

  if (state.status === "loading") return <Skeleton className="h-32" />;
  const ok = state.status === "ok";
  return (
    <div className="animate-fade-in">
      {ok ? <CheckCircle2 className="size-7 text-forest-600" /> : <XCircle className="size-7 text-crit" />}
      <h1 className="mt-3 text-[24px] font-semibold tracking-[-0.025em] text-ink-950">{ok ? "Email verified" : "Verification failed"}</h1>
      <p className="mt-2 text-[13.5px] leading-relaxed text-ink-500">
        {ok ? <>Thanks — <span className="font-medium text-ink-800">{state.message}</span> is confirmed for your account.</> : state.message}
      </p>
      <Link href={ok ? "/app" : "/app/settings"} className="mt-6 inline-flex h-10 items-center rounded-md bg-forest-700 px-4 text-[13.5px] font-medium text-white hover:bg-forest-600">
        {ok ? "Continue to dashboard" : "Request a new link"}
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}

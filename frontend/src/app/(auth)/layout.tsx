import Link from "next/link";
import { BrandNetwork } from "@/components/auth";
import { Wordmark } from "@/components/logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-paper lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      {/* Form column */}
      <div className="flex min-h-dvh flex-col px-5 py-5 sm:px-10 sm:py-7">
        <header className="flex items-center justify-between">
          <Link href="/" aria-label="ScamShield AI home" className="rounded-md">
            <Wordmark />
          </Link>
          <Link href="/" className="text-[12.5px] text-ink-500 hover:text-ink-900">Back to site</Link>
        </header>
        <main className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[372px] animate-rise">{children}</div>
        </main>
        <footer className="flex flex-wrap items-center justify-between gap-3 text-[11.5px] text-ink-400">
          <span>Sessions are HttpOnly cookies · passwords hashed with Argon2id</span>
          <nav className="flex gap-4" aria-label="Legal">
            <Link href="/privacy" className="hover:text-ink-800">Privacy</Link>
            <Link href="/terms" className="hover:text-ink-800">Terms</Link>
          </nav>
        </footer>
      </div>

      {/* Visual column (desktop) */}
      <aside className="relative hidden overflow-hidden border-l border-ink-950 bg-ink-900 lg:flex lg:flex-col" aria-hidden="false">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,rgba(58,122,92,0.28),transparent_55%),radial-gradient(ellipse_at_80%_90%,rgba(76,140,130,0.18),transparent_50%)]" />
        <div className="pointer-events-none absolute inset-0 [background-image:linear-gradient(to_right,rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.035)_1px,transparent_1px)] [background-size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_35%,transparent_80%)]" />
        <div className="relative flex items-center justify-between px-12 pt-10 text-[11px] font-medium tracking-[0.14em] text-ink-400 uppercase">
          <span>Brand protection</span>
          <span className="inline-flex items-center gap-2 font-mono tracking-normal normal-case text-ink-500">
            <span className="size-1.5 rounded-full bg-teal-400 animate-pulse-dot" /> illustration
          </span>
        </div>
        <div className="relative mx-auto flex w-full max-w-[560px] flex-1 items-center px-8 animate-fade-in">
          <BrandNetwork />
        </div>
        <div className="relative px-12 pb-12">
          <p className="max-w-md font-display text-[34px] leading-[1.08] text-ink-50">
            Your official assets, verified. <em className="text-teal-400">Everything else,</em> examined.
          </p>
          <dl className="mt-6 grid max-w-md grid-cols-3 gap-6 border-t border-ink-700 pt-5 text-[12px]">
            <div>
              <dt className="text-ink-500">Solid</dt>
              <dd className="mt-0.5 text-ink-200">Official, excluded by ID</dd>
            </div>
            <div>
              <dt className="text-ink-500">Dashed</dt>
              <dd className="mt-0.5 text-ink-200">Look-alike candidate</dd>
            </div>
            <div>
              <dt className="text-ink-500">Ringed</dt>
              <dd className="mt-0.5 text-ink-200">Flagged for review</dd>
            </div>
          </dl>
        </div>
      </aside>
    </div>
  );
}

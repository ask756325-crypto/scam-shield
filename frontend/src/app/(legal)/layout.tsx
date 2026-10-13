import Link from "next/link";
import { Wordmark } from "@/components/logo";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-paper">
      <header className="border-b border-ink-150">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-5">
          <Link href="/"><Wordmark /></Link>
          <Link href="/signin" className="text-[13px] text-ink-600 hover:text-ink-900">Sign in</Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-12 text-[14px] leading-relaxed text-ink-700 [&_h1]:text-[28px] [&_h1]:font-semibold [&_h1]:tracking-[-0.025em] [&_h1]:text-ink-950 [&_h2]:mt-9 [&_h2]:text-[16px] [&_h2]:font-semibold [&_h2]:text-ink-900 [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-5">
        {children}
      </main>
    </div>
  );
}

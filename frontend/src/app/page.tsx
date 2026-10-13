import { ArrowDown, Check } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { PlatformGlyph } from "@/components/app/bits";
import { LogoMark } from "@/components/logo";
import { HeroPreview } from "@/components/marketing/hero-preview";
import { NAV_LINKS } from "@/components/marketing/links";
import { MarketingNav, PrimaryCta } from "@/components/marketing/nav";
import { AppPreview, AssetsPreview, InvestigationPreview, NOT_INTEGRATED, NotIntegratedIcon, SocialPreview, SOURCES } from "@/components/marketing/previews";
import { Reveal } from "@/components/marketing/reveal";

export const metadata: Metadata = {
  title: "ScamShield AI — Find brand impersonation on social platforms and app stores",
  description:
    "ScamShield AI searches Bluesky, Mastodon, the App Store and Google Play for accounts and apps posing as your brand, excludes your official assets, and explains every finding.",
};

const container = "mx-auto w-full max-w-[1200px] px-5 md:px-8";

function Eyebrow({ n, children, dark }: { n: string; children: ReactNode; dark?: boolean }) {
  return (
    <div className={`flex items-center gap-3 text-[11.5px] font-medium tracking-[0.14em] uppercase ${dark ? "text-teal-400" : "text-teal-700"}`}>
      <span className="font-mono tracking-normal opacity-70">{n}</span>
      <span className={`h-px w-6 ${dark ? "bg-teal-400/40" : "bg-teal-700/30"}`} aria-hidden />
      {children}
    </div>
  );
}

function Points({ items, dark }: { items: ReactNode[]; dark?: boolean }) {
  return (
    <ul className="mt-6 space-y-3">
      {items.map((t, i) => (
        <li key={i} className={`flex gap-3 text-[14px] leading-relaxed ${dark ? "text-ink-300" : "text-ink-600"}`}>
          <Check className={`mt-1 size-4 shrink-0 ${dark ? "text-teal-400" : "text-forest-600"}`} aria-hidden />
          <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

function FeatureSection({
  id, n, eyebrow, title, body, points, visual, flip, tone = "light",
}: {
  id: string; n: string; eyebrow: string; title: ReactNode; body: ReactNode; points: ReactNode[]; visual: ReactNode; flip?: boolean; tone?: "light" | "paper" | "dark";
}) {
  const dark = tone === "dark";
  const bg = { light: "bg-ink-50", paper: "bg-paper border-y border-ink-150", dark: "bg-ink-900" }[tone];
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={`${bg} py-20 md:py-28`}>
      <div className={`${container} grid items-center gap-12 lg:gap-16 ${flip ? "lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]" : "lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]"}`}>
        <Reveal className={flip ? "min-w-0 lg:order-2" : "min-w-0"}>
          <Eyebrow n={n} dark={dark}>{eyebrow}</Eyebrow>
          <h2 id={`${id}-title`} className={`mt-4 text-balance text-[30px] leading-[1.12] font-semibold tracking-[-0.03em] md:text-[36px] ${dark ? "text-ink-50" : "text-ink-950"}`}>
            {title}
          </h2>
          <p className={`mt-4 max-w-xl text-[15.5px] leading-relaxed ${dark ? "text-ink-300" : "text-ink-600"}`}>{body}</p>
          <Points items={points} dark={dark} />
        </Reveal>
        <Reveal delay={120} className={flip ? "min-w-0 lg:order-1" : "min-w-0"}>
          {visual}
        </Reveal>
      </div>
    </section>
  );
}

const WORKFLOW = [
  { n: "01", title: "Describe the brand", body: "Names, aliases, official domains, logo, and every official account and app ID." },
  { n: "02", title: "Collect candidates", body: "Bounded look-alike searches across connected sources — on demand or on a schedule." },
  { n: "03", title: "Exclude, then score", body: "Official assets are removed by exact identifier. Everything else is scored on independent evidence." },
  { n: "04", title: "Review and decide", body: "Confirm or mark safe from a keyboard-driven queue. Every decision is recorded." },
  { n: "05", title: "Track changes", body: "Rescans flag what is new, changed, recurring or no longer observed — and reopen safe items that change." },
];

export default function Landing() {
  return (
    <div className="bg-ink-50">
      <MarketingNav />

      <main id="main">
        {/* 1 · Hero */}
        <section aria-labelledby="hero-title" className="relative isolate overflow-hidden bg-ink-900 pt-28 pb-20 md:pt-36 md:pb-28">
          <div aria-hidden className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_80%_60%_at_15%_0%,rgba(41,97,72,0.55),transparent_60%),radial-gradient(ellipse_60%_55%_at_95%_35%,rgba(76,140,130,0.22),transparent_60%),linear-gradient(180deg,#161819_0%,#121514_100%)]" />
          <div aria-hidden className="absolute inset-0 -z-10 [background-image:linear-gradient(to_right,rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.04)_1px,transparent_1px)] [background-size:64px_64px] [mask-image:radial-gradient(ellipse_70%_60%_at_40%_30%,black,transparent_75%)]" />
          <div className={`${container} grid items-center gap-14 lg:grid-cols-[1.02fr_1fr]`}>
            <div>
              <p className="animate-rise text-[12px] font-medium tracking-[0.16em] text-teal-400 uppercase">Digital risk protection</p>
              <h1 id="hero-title" className="animate-rise mt-5 text-balance font-display text-[44px] leading-[1.02] text-ink-50 [animation-delay:60ms] sm:text-[56px] lg:text-[64px]">
                Find the accounts and apps <em className="text-teal-400">posing</em> as your brand.
              </h1>
              <p className="animate-rise mt-6 max-w-[34rem] text-[16.5px] leading-relaxed text-ink-300 [animation-delay:120ms]">
                ScamShield searches social platforms and mobile app stores for look-alikes, sets your official assets aside,
                and shows the evidence behind every finding — so your team reviews what matters.
              </p>
              <div className="animate-rise mt-9 flex flex-wrap items-center gap-3 [animation-delay:180ms]">
                <PrimaryCta size="lg" tone="forest" />
                <a href="#workflow" className="group inline-flex h-11 items-center gap-2 rounded-md border border-white/15 px-5 text-[14px] text-ink-100 transition-colors hover:border-white/30 hover:bg-white/[0.04]">
                  How monitoring works
                  <ArrowDown className="size-4 transition-transform duration-200 group-hover:translate-y-0.5" aria-hidden />
                </a>
              </div>
              <dl className="animate-rise mt-12 grid max-w-md grid-cols-2 gap-6 border-t border-white/10 pt-6 [animation-delay:240ms]">
                <div>
                  <dt className="text-[12px] text-ink-500">Social</dt>
                  <dd className="mt-1 text-[13.5px] text-ink-200">Bluesky · Mastodon</dd>
                </div>
                <div>
                  <dt className="text-[12px] text-ink-500">App stores</dt>
                  <dd className="mt-1 text-[13.5px] text-ink-200">App Store · Google Play</dd>
                </div>
              </dl>
            </div>
            <div className="animate-rise [animation-delay:160ms]">
              <HeroPreview />
            </div>
          </div>
        </section>

        {/* 2 · Social impersonation */}
        <FeatureSection
          id="social"
          n="01"
          eyebrow="Social impersonation"
          title="Spot fake support accounts before your customers message them."
          body="Look-alike profiles copy names, avatars and bios, then move victims to private chats. ScamShield compares every candidate against your brand on several independent signals."
          points={[
            "Catches homoglyphs, leetspeak, spacing tricks, typos and added words like “support” or “official”.",
            "Compares avatars to your logo with perceptual hashing — re-encoded or recoloured copies still match.",
            "Reads bios and links for giveaways, wallet requests, shorteners and off-platform contact.",
          ]}
          visual={<SocialPreview />}
        />

        {/* 3 · Suspicious apps */}
        <FeatureSection
          id="apps"
          n="02"
          eyebrow="Suspicious app discovery"
          title="Surface app listings that borrow your name, icon and description."
          body="Fake wallet and “login” apps rely on looking official. ScamShield checks who actually publishes each listing and how closely it copies yours."
          points={[
            "Verifies developers by publisher ID — a matching display name is never treated as proof.",
            "Measures icon similarity and description overlap with your official listings.",
            "Labels tutorial and utility apps that only mention you as low risk instead of flooding the queue.",
          ]}
          visual={<AppPreview />}
          flip
          tone="paper"
        />

        {/* 4 · Official-asset protection */}
        <FeatureSection
          id="assets"
          n="03"
          eyebrow="Brand identity & official assets"
          title="Your own accounts never land in the review queue."
          body="A brand profile records who you are: names, domains, logo, and every official account and app. Official assets are set aside by exact identifier before anything is scored — with an audit trail."
          points={[
            "Matches platform handles, profile URLs, account IDs, bundle and package IDs, and Apple track IDs.",
            "Recognises Bluesky handles on your domains and Mastodon profiles your site links back to.",
            "Records every exclusion, so you can see exactly why something was set aside.",
          ]}
          visual={<AssetsPreview />}
          tone="dark"
        />

        {/* 5 · Evidence-based investigations */}
        <FeatureSection
          id="investigations"
          n="04"
          eyebrow="Evidence-based investigations"
          title="Every finding explains itself."
          body="A similar name is not a verdict. Findings rise above “low” only when independent evidence agrees, and each one shows which signals were evaluated, which weren’t, and why."
          points={[
            "Correlated signals count once; missing data is listed as “not evaluated”, never guessed.",
            "Scores are heuristic triage evidence, and every finding is marked “review required”.",
            "Confirm or mark safe with a note; decisions and changes are kept in the finding’s history.",
          ]}
          visual={<InvestigationPreview />}
          flip
        />

        {/* 6 · Source coverage */}
        <section id="sources" aria-labelledby="sources-title" className="border-y border-ink-150 bg-paper py-20 md:py-28">
          <div className={container}>
            <Reveal className="max-w-2xl">
              <Eyebrow n="05">Source coverage</Eyebrow>
              <h2 id="sources-title" className="mt-4 text-balance text-[30px] leading-[1.12] font-semibold tracking-[-0.03em] text-ink-950 md:text-[36px]">
                Clear about what we watch — and what we don’t.
              </h2>
              <p className="mt-4 text-[15.5px] leading-relaxed text-ink-600">
                ScamShield uses public, permitted endpoints only. Each scan reports every source’s real outcome: a failing source is shown as failing, never quietly
                filled in with sample data.
              </p>
            </Reveal>
            <Reveal delay={100} className="mt-10 overflow-hidden rounded-xl border border-ink-150 bg-white">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13.5px]">
                  <caption className="sr-only">Connected sources and how they are accessed</caption>
                  <thead className="border-b border-ink-150 bg-ink-50 text-[12px] text-ink-500">
                    <tr>
                      <th scope="col" className="py-3 pr-4 pl-5 font-medium">Source</th>
                      <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">Access</th>
                      <th scope="col" className="px-4 py-3 font-medium">Integration</th>
                      <th scope="col" className="hidden py-3 pr-5 pl-4 font-medium lg:table-cell">Good to know</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-150">
                    {SOURCES.map((s) => (
                      <tr key={s.name}>
                        <th scope="row" className="py-3.5 pr-4 pl-5 font-medium text-ink-900">
                          <span className="inline-flex items-center gap-2"><PlatformGlyph platform={s.platform} className="text-ink-500" /> {s.name}</span>
                          <span className="mt-1 block text-[12.5px] font-normal text-ink-500 md:hidden">{s.access}</span>
                          <span className="mt-0.5 block text-[12.5px] font-normal text-ink-500 lg:hidden">{s.note}</span>
                        </th>
                        <td className="hidden px-4 py-3.5 text-ink-600 md:table-cell">{s.access}</td>
                        <td className="px-4 py-3.5">
                          <span className={`inline-flex rounded-[4px] border px-1.5 py-0.5 text-[11.5px] font-medium ${s.kind === "Unofficial" ? "border-[#ebdcae] bg-med-bg text-med" : "border-forest-100 bg-forest-50 text-forest-700"}`}>{s.kind}</span>
                        </td>
                        <td className="hidden py-3.5 pr-5 pl-4 text-ink-500 lg:table-cell">{s.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-ink-150 bg-ink-50/60 px-5 py-3.5 text-[13px] text-ink-600">
                <span className="font-medium text-ink-800">Not integrated:</span>
                {NOT_INTEGRATED.map((n) => (
                  <span key={n} className="inline-flex items-center gap-1.5"><NotIntegratedIcon /> {n}</span>
                ))}
                <span className="text-ink-500">— no permitted public search access without approved credentials.</span>
              </div>
            </Reveal>
          </div>
        </section>

        {/* 7 · Workflow */}
        <section id="workflow" aria-labelledby="workflow-title" className="bg-ink-50 py-20 md:py-28">
          <div className={container}>
            <Reveal className="max-w-2xl">
              <Eyebrow n="06">How monitoring works</Eyebrow>
              <h2 id="workflow-title" className="mt-4 text-balance text-[30px] leading-[1.12] font-semibold tracking-[-0.03em] text-ink-950 md:text-[36px]">
                From brand profile to a decision your team can stand behind.
              </h2>
            </Reveal>
            <ol className="mt-12 grid gap-px overflow-hidden rounded-xl border border-ink-150 bg-ink-150 sm:grid-cols-2 lg:grid-cols-5">
              {WORKFLOW.map((s, i) => (
                <Reveal as="li" key={s.n} delay={i * 70} className="group relative bg-paper p-6 transition-colors duration-300 hover:bg-white">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[12px] text-teal-600">{s.n}</span>
                    <span className="h-px flex-1 bg-ink-150 transition-colors duration-300 group-hover:bg-teal-200" aria-hidden />
                  </div>
                  <h3 className="mt-5 text-[15px] font-semibold text-ink-900">{s.title}</h3>
                  <p className="mt-2 text-[13.5px] leading-relaxed text-ink-500">{s.body}</p>
                </Reveal>
              ))}
            </ol>
            <Reveal className="mt-6 text-[13px] text-ink-500">
              Want to see it end to end without connecting anything? Every workspace can load a clearly labelled synthetic demo brand that runs offline.
            </Reveal>
          </div>
        </section>

        {/* 8 · Final CTA */}
        <section aria-labelledby="cta-title" className="px-5 pb-20 md:px-8 md:pb-28">
          <Reveal className="relative isolate mx-auto max-w-[1200px] overflow-hidden rounded-2xl bg-forest-800 px-7 py-14 md:px-14 md:py-16">
            <div aria-hidden className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_60%_80%_at_100%_100%,rgba(76,140,130,0.45),transparent_65%),radial-gradient(ellipse_50%_70%_at_0%_0%,rgba(18,48,31,0.9),transparent_70%)]" />
            <div className="flex flex-wrap items-end justify-between gap-8">
              <div className="max-w-xl">
                <h2 id="cta-title" className="font-display text-[36px] leading-[1.06] text-ink-50 md:text-[44px]">Know what’s using your name.</h2>
                <p className="mt-3 text-[15px] leading-relaxed text-forest-200">Create a workspace, describe your brand, and run your first scan in minutes.</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <PrimaryCta size="lg" />
                <a href="#workflow" className="inline-flex h-11 items-center rounded-md border border-white/20 px-5 text-[14px] text-ink-50 transition-colors hover:bg-white/[0.06]">See the workflow</a>
              </div>
            </div>
          </Reveal>
        </section>
      </main>

      {/* 9 · Footer */}
      <footer className="border-t border-ink-150 bg-paper">
        <div className={`${container} grid gap-10 py-12 sm:grid-cols-2 md:grid-cols-[1.4fr_1fr_1fr_1fr]`}>
          <div>
            <Link href="/" className="inline-flex items-center gap-2 rounded-md" aria-label="ScamShield AI home">
              <LogoMark className="size-6" />
              <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink-950">ScamShield <span className="text-teal-600">AI</span></span>
            </Link>
            <p className="mt-3 max-w-xs text-[13px] leading-relaxed text-ink-500">Brand impersonation discovery for social platforms and mobile app stores.</p>
          </div>
          <nav aria-label="Product">
            <h3 className="text-[12px] font-medium tracking-wide text-ink-400 uppercase">Product</h3>
            <ul className="mt-3 space-y-2 text-[13.5px]">
              {NAV_LINKS.map((l) => (
                <li key={l.href}><a href={l.href} className="text-ink-600 hover:text-ink-950">{l.label}</a></li>
              ))}
            </ul>
          </nav>
          <nav aria-label="Account">
            <h3 className="text-[12px] font-medium tracking-wide text-ink-400 uppercase">Account</h3>
            <ul className="mt-3 space-y-2 text-[13.5px]">
              <li><Link href="/signin" className="text-ink-600 hover:text-ink-950">Sign in</Link></li>
              <li><Link href="/signup" className="text-ink-600 hover:text-ink-950">Create account</Link></li>
              <li><Link href="/forgot-password" className="text-ink-600 hover:text-ink-950">Reset password</Link></li>
              <li><Link href="/app" className="text-ink-600 hover:text-ink-950">Dashboard</Link></li>
            </ul>
          </nav>
          <nav aria-label="Legal">
            <h3 className="text-[12px] font-medium tracking-wide text-ink-400 uppercase">Legal</h3>
            <ul className="mt-3 space-y-2 text-[13.5px]">
              <li><Link href="/privacy" className="text-ink-600 hover:text-ink-950">Privacy</Link></li>
              <li><Link href="/terms" className="text-ink-600 hover:text-ink-950">Terms</Link></li>
            </ul>
          </nav>
        </div>
        <div className="border-t border-ink-150">
          <div className={`${container} flex flex-wrap items-center justify-between gap-3 py-5 text-[12px] text-ink-400`}>
            <span>Built for the byteXL HacXLerate Challenge 03.</span>
            <span>Product previews use a fictional brand and illustrative data.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

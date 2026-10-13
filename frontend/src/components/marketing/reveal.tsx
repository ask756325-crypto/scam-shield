"use client";

import { useEffect, useRef, type ElementType, type ReactNode } from "react";

/**
 * Scroll reveal. Content is fully visible without JavaScript: the hidden starting state only applies under
 * `html.js` (set by an inline script in the root layout) and is skipped entirely for reduced-motion users.
 * Only opacity/transform animate, so there is no layout shift.
 */
export function Reveal({ children, delay = 0, as: Tag = "div", className }: { children: ReactNode; delay?: number; as?: ElementType; className?: string }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
      el.dataset.shown = "";
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            el.dataset.shown = "";
            io.disconnect();
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} data-reveal="" style={delay ? { transitionDelay: `${delay}ms` } : undefined} className={className}>
      {children}
    </Tag>
  );
}

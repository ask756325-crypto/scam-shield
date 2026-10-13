"use client";

import { Check, Eye, EyeOff, X } from "lucide-react";
import { forwardRef, useState, type InputHTMLAttributes } from "react";
import { Input, cx } from "./ui";

// ---------------------------------------------------------------- Password field with show/hide

export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, "type">>(function PasswordInput(
  { className, ...rest },
  ref,
) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input ref={ref} type={shown ? "text" : "password"} className={cx("pr-10", className)} spellCheck={false} autoCapitalize="none" {...rest} />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide password" : "Show password"}
        aria-pressed={shown}
        aria-controls={rest.id}
        className="absolute top-1/2 right-1.5 grid size-7 -translate-y-1/2 place-items-center rounded text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-700"
      >
        {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
});

// ---------------------------------------------------------------- Password policy (mirrors backend security.password_problems)

export function passwordChecks(pw: string, email: string) {
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { id: "len", label: "At least 10 characters", ok: pw.length >= 10 },
    { id: "mix", label: "Letters plus numbers or symbols", ok: /[A-Za-z]/.test(pw) && /[^A-Za-z]/.test(pw) },
    { id: "email", label: "Doesn’t contain your email name", ok: !pw || local.length < 4 ? true : !pw.toLowerCase().includes(local) },
  ];
}

export function PasswordChecklist({ password, email, id }: { password: string; email: string; id?: string }) {
  const checks = passwordChecks(password, email);
  return (
    <ul id={id} className="mt-2 grid gap-1" aria-live="polite">
      {checks.map((c) => (
        <li key={c.id} className={cx("flex items-center gap-1.5 text-[12px] transition-colors duration-200", !password ? "text-ink-400" : c.ok ? "text-forest-600" : "text-ink-500")}>
          <span className={cx("grid size-3.5 place-items-center rounded-full transition-colors duration-200", !password ? "bg-ink-100" : c.ok ? "bg-forest-100" : "bg-ink-100")}>
            {password && c.ok ? <Check className="size-2.5" strokeWidth={3} /> : password ? <X className="size-2.5 text-ink-400" strokeWidth={3} /> : null}
          </span>
          {c.label}
          <span className="sr-only">{c.ok ? " — met" : " — not met"}</span>
        </li>
      ))}
    </ul>
  );
}

export function FieldError({ id, message }: { id: string; message?: string | null }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="animate-fade-in text-[12px] text-crit">
      {message}
    </p>
  );
}

// ---------------------------------------------------------------- Brand-protection visual

/*
 * A brand at the centre, its official assets on an inner ring (solid, verified), and look-alike candidates
 * drifting at the edge (dashed). Two candidates are flagged, one is set aside as unrelated. A slow scan arc
 * sweeps the field. Pure SVG; motion is CSS and disabled under prefers-reduced-motion.
 */
const OFFICIAL = [
  { x: 300, y: 158, label: "northvale.example", kind: "domain" },
  { x: 432, y: 262, label: "iOS · com.northvale", kind: "app" },
  { x: 372, y: 418, label: "@northvale", kind: "handle" },
  { x: 196, y: 404, label: "Play · com.northvale", kind: "app" },
  { x: 158, y: 250, label: "@northvale.social", kind: "handle" },
];
const CANDIDATES = [
  { x: 470, y: 112, label: "n0rthvale-help", flag: "crit" },
  { x: 520, y: 372, label: "northvaIe wallet", flag: "high" },
  { x: 88, y: 132, label: "northvale hikes", flag: "none" },
  { x: 66, y: 386, label: "nrthvale login", flag: "watch" },
  { x: 318, y: 540, label: "northvale fans", flag: "none" },
];

/** Places a label radially outward from the centre so connecting lines (which arrive from the centre) never cross it. */
function NodeLabel({ x, y, r, fill, children }: { x: number; y: number; r: number; fill: string; children: string }) {
  const dx = x - 300, dy = y - 300;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const gap = r + 8;
  const anchor = ux > 0.35 ? "start" : ux < -0.35 ? "end" : "middle";
  const tx = x + ux * gap;
  const ty = y + uy * gap + (Math.abs(uy) > 0.6 ? (uy > 0 ? 8 : -2) : 3.5);
  return (
    <text x={tx} y={ty} textAnchor={anchor} fill={fill} className="font-mono" fontSize="10.5">
      {children}
    </text>
  );
}

export function BrandNetwork() {
  const cx0 = 300, cy0 = 300;
  return (
    <svg viewBox="-110 0 820 600" className="h-full w-full" role="img" aria-label="Illustration: a brand surrounded by its verified official assets, with look-alike accounts at the edge being evaluated">
      <defs>
        <radialGradient id="bn-core" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#4c8c82" stopOpacity="0.55" />
          <stop offset="0.55" stopColor="#1f4d3a" stopOpacity="0.18" />
          <stop offset="1" stopColor="#1f4d3a" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="bn-sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#73a79d" stopOpacity="0" />
          <stop offset="1" stopColor="#73a79d" stopOpacity="0.16" />
        </linearGradient>
        <linearGradient id="bn-shield" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3a7a5c" />
          <stop offset="1" stopColor="#4c8c82" />
        </linearGradient>
      </defs>

      {/* concentric guides */}
      <circle cx={cx0} cy={cy0} r="230" fill="url(#bn-core)" />
      {[80, 150, 230].map((r) => (
        <circle key={r} cx={cx0} cy={cy0} r={r} fill="none" stroke="#e4e1da" strokeOpacity={r === 150 ? 0.16 : 0.08} strokeDasharray={r === 230 ? "2 6" : undefined} />
      ))}

      {/* scan sweep (blurred so it reads as light, not a shape) */}
      <filter id="bn-blur" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="7" />
      </filter>
      <g className="bn-sweep" filter="url(#bn-blur)" style={{ transformOrigin: `${cx0}px ${cy0}px` }}>
        <path d={`M${cx0},${cy0} L${cx0 + 245},${cy0} A245,245 0 0,0 ${cx0 + 245 * Math.cos(-0.5)},${cy0 + 245 * Math.sin(-0.5)} Z`} fill="url(#bn-sweep)" />
      </g>

      {/* candidate links (dashed) */}
      {CANDIDATES.map((c, i) => (
        <line key={`cl${i}`} x1={cx0} y1={cy0} x2={c.x} y2={c.y} stroke={c.flag === "crit" ? "#d9826f" : c.flag === "high" ? "#d9a46f" : "#8e9396"} strokeOpacity={c.flag === "none" ? 0.18 : 0.45} strokeWidth="1" strokeDasharray="3 5" className="bn-dash" />
      ))}
      {/* official links (solid) */}
      {OFFICIAL.map((o, i) => (
        <line key={`ol${i}`} x1={cx0} y1={cy0} x2={o.x} y2={o.y} stroke="#73a79d" strokeOpacity="0.55" strokeWidth="1.2" />
      ))}

      {/* official nodes */}
      {OFFICIAL.map((o, i) => (
        <g key={`on${i}`} className="bn-node" style={{ animationDelay: `${120 + i * 70}ms` }}>
          <circle cx={o.x} cy={o.y} r="13" fill="#12301f" stroke="#73a79d" strokeWidth="1.2" />
          <path d={`M${o.x - 4},${o.y} l3,3 l6,-6`} fill="none" stroke="#c4dcd7" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          <NodeLabel x={o.x} y={o.y} r={13} fill="#b8bbbb">{o.label}</NodeLabel>
        </g>
      ))}

      {/* candidate nodes */}
      {CANDIDATES.map((c, i) => {
        const ring = c.flag === "crit" ? "#e08b78" : c.flag === "high" ? "#dcae7a" : c.flag === "watch" ? "#b8bbbb" : "#6a6f72";
        return (
          <g key={`cn${i}`} className="bn-node" style={{ animationDelay: `${500 + i * 90}ms` }}>
            {(c.flag === "crit" || c.flag === "high") && <circle cx={c.x} cy={c.y} r="15" fill="none" stroke={ring} strokeOpacity="0.4" className="bn-pulse" style={{ transformOrigin: `${c.x}px ${c.y}px` }} />}
            <circle cx={c.x} cy={c.y} r="8" fill="#161819" stroke={ring} strokeWidth="1.2" strokeDasharray={c.flag === "none" ? "2 2.5" : undefined} />
            <NodeLabel x={c.x} y={c.y} r={8} fill={c.flag === "none" ? "#6a6f72" : "#b8bbbb"}>{c.label}</NodeLabel>
          </g>
        );
      })}

      {/* brand core */}
      <g className="bn-node">
        <circle cx={cx0} cy={cy0} r="34" fill="#161819" stroke="#4c8c82" strokeOpacity="0.7" />
        <g transform={`translate(${cx0 - 15} ${cy0 - 16}) scale(0.94)`}>
          <path d="M16 2.5 4.5 6.8v8.4c0 7.1 4.9 12.4 11.5 14.3 6.6-1.9 11.5-7.2 11.5-14.3V6.8L16 2.5Z" fill="url(#bn-shield)" />
          <rect x="8" y="14.6" width="16" height="2" rx="1" fill="#f4f2ec" />
          <circle cx="21.5" cy="15.6" r="2.6" fill="none" stroke="#f4f2ec" strokeWidth="1.8" />
        </g>
      </g>

      <style>{`
        .bn-node { animation: bn-in 520ms cubic-bezier(.2,.7,.2,1) both; }
        .bn-sweep { animation: bn-rotate 14s linear infinite; }
        .bn-pulse { animation: bn-pulse 2.6s ease-out infinite; }
        .bn-dash { animation: bn-dash 6s linear infinite; }
        @keyframes bn-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes bn-rotate { to { transform: rotate(360deg); } }
        @keyframes bn-pulse { 0% { transform: scale(.8); opacity: .7; } 100% { transform: scale(1.7); opacity: 0; } }
        @keyframes bn-dash { to { stroke-dashoffset: -64; } }
        @media (prefers-reduced-motion: reduce) { .bn-node, .bn-sweep, .bn-pulse, .bn-dash { animation: none !important; } }
      `}</style>
    </svg>
  );
}

export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function messageFrom(data: unknown, status: number): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  if (status === 429) return "Too many requests. Please wait a moment.";
  if (status >= 500) return "The server had a problem. Please try again.";
  return `Request failed (${status})`;
}

type Opts = Omit<RequestInit, "body"> & { body?: unknown; query?: Record<string, string | number | boolean | string[] | undefined | null> };

export function buildQuery(query?: Opts["query"]): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else p.append(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  return (await request<T>(path, opts)).data;
}

/** Like `api`, plus the total match count a list endpoint reports in X-Total-Count. */
export async function apiPage<T = unknown>(path: string, opts: Opts = {}): Promise<{ data: T; total: number }> {
  const { data, res } = await request<T>(path, opts);
  return { data, total: Number(res.headers.get("X-Total-Count") ?? 0) };
}

async function request<T>(path: string, opts: Opts): Promise<{ data: T; res: Response }> {
  const { body, query, headers, ...rest } = opts;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(`/api${path}${buildQuery(query)}`, {
      credentials: "same-origin",
      ...rest,
      headers: {
        "X-ScamShield-CSRF": "1",
        ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Can’t reach the server. Check your connection and try again.");
  }
  const text = await res.text();
  let data: unknown = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (!res.ok) {
    // Only bounce from inside the app: auth pages probe /auth/me and expect a silent 401 (no redirect loops).
    if (res.status === 401 && typeof window !== "undefined" && window.location.pathname.startsWith("/app")) {
      const expired = res.headers.get("X-Session-State") === "expired" ? "&reason=expired" : "";
      window.location.href = `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}${expired}`;
    }
    throw new ApiError(res.status, messageFrom(data, res.status), data);
  }
  return { data: data as T, res };
}

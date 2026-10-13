import { NextResponse, type NextRequest } from "next/server";

// UX-only gate: redirects visitors without a session cookie away from /app. Real authorization is
// enforced by the backend on every API call (an invalid cookie still gets 401 and is bounced client-side).
export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has("ss_session");
  const { pathname, search } = req.nextUrl;
  if (pathname.startsWith("/app") && !hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/signin";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/app/:path*"] };

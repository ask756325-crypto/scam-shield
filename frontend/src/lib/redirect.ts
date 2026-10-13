/** Only same-app, relative destinations are honoured (prevents open redirects and loops back to auth pages). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/app") || next.startsWith("//") || next.includes("\\")) return "/app";
  return next;
}

import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-Pass-2026!";
let counter = 0;

export function uniqueEmail(prefix = "e2e") {
  counter += 1;
  return `${prefix}-${Date.now()}-${counter}@example.com`;
}

/** Create an account through the API (fast path for tests that aren't about sign-up). Cookies land in the page context. */
export async function signUpViaApi(page: Page, org = "E2E Org") {
  const email = uniqueEmail();
  const r = await page.request.post("/api/auth/signup", {
    headers: { "X-ScamShield-CSRF": "1" },
    data: { email, password: PASSWORD, name: "E2E Analyst", organization: org },
  });
  expect(r.status(), await r.text()).toBe(201);
  return email;
}

/** Add the synthetic demo brand and run one demo scan via the API; returns the brand id. */
export async function demoBrandWithScan(page: Page) {
  const brand = await (await page.request.post("/api/demo/brand", { headers: { "X-ScamShield-CSRF": "1" } })).json();
  const scan = await (await page.request.post(`/api/brands/${brand.id}/scans`, { headers: { "X-ScamShield-CSRF": "1" }, data: {} })).json();
  await expect
    .poll(async () => (await (await page.request.get(`/api/scans/${scan.id}`)).json()).status, { timeout: 30_000 })
    .toMatch(/completed|partial/);
  return brand.id as number;
}

import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { demoBrandWithScan, PASSWORD, signUpViaApi } from "./helpers";

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits) for driving the 2FA flow. */
function totp(secret: string, offsetSteps = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/\s|=/g, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + offsetSteps));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function confirmFinding(page: Page, brandId: number, q: string) {
  const f = (await (await page.request.get(`/api/findings?brand_id=${brandId}&q=${encodeURIComponent(q)}`)).json()).items[0];
  await page.request.post(`/api/findings/${f.id}/decision`, { headers: { "X-ScamShield-CSRF": "1" }, data: { action: "confirm", note: "" } });
  return f.id as number;
}

test.describe("analyst power features", () => {
  test("accuracy panel, notifications, audit log", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app/settings?tab=detection");
    await expect(page.getByText("Accuracy on your analysts’ decisions")).toBeVisible();
    await expect(page.getByText(/No live findings have been confirmed/)).toBeVisible(); // honest empty state
    await expect(page.getByText("Regression benchmark")).toBeVisible();
    await page.getByRole("button", { name: /Show all \d+ cases/ }).click();
    await expect(page.getByText("quiet impersonator (no links, no scam text)", { exact: false })).toBeVisible();

    await page.getByRole("radio", { name: "Notifications" }).click();
    await expect(page.getByText(/No SMTP server is configured/)).toBeVisible();
    await page.getByText("New high findings", { exact: true }).click();
    await page.getByRole("button", { name: "Save preferences" }).click();
    await expect(page.getByText("Notification preferences saved")).toBeVisible();
    await page.getByRole("button", { name: "Send test" }).first().click();
    await expect(page.getByText("Test email: logged")).toBeVisible(); // never claims "sent" without SMTP
    await expect(page.getByText("Development mode: written to the server log (no SMTP)").first()).toBeVisible();

    await page.getByRole("radio", { name: "Audit log" }).click();
    await expect(page.getByLabel("Activity type")).toBeVisible();
    await expect(page.getByText("security.", { exact: false }).or(page.getByText("No activity recorded yet."))).toBeVisible();
  });

  test("takedown case from a confirmed finding, tracked on the Takedowns page", async ({ page }) => {
    await signUpViaApi(page);
    const brandId = await demoBrandWithScan(page);
    const fid = await confirmFinding(page, brandId, "N0rthvale");
    await page.goto(`/app/investigations/${fid}`);
    await page.getByRole("button", { name: "Open takedown case" }).click();
    await expect(page.getByText("Takedown case opened")).toBeVisible();
    await expect(page.getByText(/Bluesky — report the account in the app/)).toBeVisible();
    await expect(page.locator("pre").filter({ hasText: "Impersonation of Northvale Pay" })).toBeVisible();
    await page.getByLabel("Platform reference").fill("BSKY-42");
    await page.getByRole("button", { name: "Mark reported" }).click();
    await expect(page.getByText("Takedown updated")).toBeVisible();
    await page.goto("/app/takedowns");
    const row = page.getByRole("row", { name: /N0rthvale Pay/ });
    await expect(row).toContainText("Reported");
    await expect(row).toContainText("BSKY-42");
  });

  test("bulk triage, campaigns and look-alike preview", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/investigations");
    const rowBoxes = page.getByRole("checkbox", { name: /^Select (?!all)/ });
    await rowBoxes.nth(0).check();
    await rowBoxes.nth(1).check();
    await expect(page.getByText("2 selected")).toBeVisible();
    await page.getByRole("toolbar", { name: "Bulk actions" }).getByRole("button", { name: "Further review" }).click();
    await expect(page.getByText("2 updated")).toBeVisible();
    await page.getByLabel("Assignee").selectOption("unassigned");

    await page.goto("/app/campaigns");
    await expect(page.getByText(/Possible campaign — 2 findings share/).first()).toBeVisible();
    await expect(page.getByText(/does not by itself prove the accounts have the same owner/)).toBeVisible();

    await page.goto("/app/brands/new");
    await page.getByLabel("Brand name").fill("Kestrel Bank");
    await page.getByRole("button", { name: /Preview look-alikes/ }).click();
    await expect(page.getByText("K3strel Bank", { exact: true })).toBeVisible();
    await expect(page.getByText("kestrelbank-login.top")).toBeVisible();
  });

  test("two-factor setup and two-step sign-in", async ({ page, context }) => {
    const email = await signUpViaApi(page);
    await page.goto("/app/settings");
    await page.getByRole("button", { name: "Set up two-factor authentication" }).click();
    await page.getByLabel("Confirm your password").fill(PASSWORD);
    await page.getByRole("button", { name: "Continue" }).click();
    const secret = (await page.getByLabel("Setup key").textContent())!.replace(/\s/g, "");
    await page.getByLabel(/Enter the 6-digit code/).fill(totp(secret));
    await page.getByRole("button", { name: "Turn on" }).click();
    await expect(page.getByLabel("Recovery codes")).toBeVisible();
    await page.getByRole("button", { name: "I’ve saved them" }).click();
    await expect(page.getByText(/recovery codes? left/)).toBeVisible();

    await context.clearCookies();
    await page.goto("/signin");
    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: /Two-factor check/ })).toBeVisible();
    await page.getByLabel("Authentication code").fill("000000");
    await page.getByRole("button", { name: "Verify and sign in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Incorrect code" })).toBeVisible();
    await page.getByLabel("Authentication code").fill(totp(secret, 1)); // the current code was used by "Turn on"
    await page.getByRole("button", { name: "Verify and sign in" }).click();
    await expect(page).toHaveURL(/\/app/);
  });
});

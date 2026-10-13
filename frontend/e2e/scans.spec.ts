import { expect, test } from "@playwright/test";
import { demoBrandWithScan, signUpViaApi } from "./helpers";

const CSRF = { "X-ScamShield-CSRF": "1" };

async function scanAndWait(page: import("@playwright/test").Page, brandId: number) {
  const scan = await (await page.request.post(`/api/brands/${brandId}/scans`, { headers: CSRF, data: {} })).json();
  await expect
    .poll(async () => (await (await page.request.get(`/api/scans/${scan.id}`)).json()).status, { timeout: 30_000 })
    .toMatch(/completed|partial/);
  return scan.id as number;
}

test.describe("scan history and scheduled monitoring", () => {
  test("configure, pause, resume and disable a time-zone-aware schedule", async ({ page }) => {
    await signUpViaApi(page);
    const brandId = await demoBrandWithScan(page);
    await page.goto(`/app/brands/${brandId}?tab=monitoring`);
    await expect(page.getByText("Monitoring schedule")).toBeVisible();
    // The e2e stack runs without a scheduler process: the UI must say so rather than imply scans will run.
    await expect(page.getByText("Scheduler not running.")).toBeVisible();

    await page.getByRole("radio", { name: "Weekly" }).click();
    await page.getByLabel("Local time").fill("07:45");
    await page.getByLabel("Time zone").selectOption("Asia/Tokyo");
    await page.getByRole("button", { name: "Wed" }).click();
    await page.getByRole("button", { name: "Save schedule" }).click();
    await expect(page.getByText("Weekly on Mon, Wed at 07:45 (Asia/Tokyo)")).toHaveCount(2); // schedule card + top-bar chip
    await expect(page.getByText("Next runs")).toBeVisible();
    await expect(page.getByText(/07:45.*Asia\/Tokyo/).first()).toBeVisible();

    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByText("Paused by an analyst")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Paused", { exact: true })).toBeVisible(); // persisted
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("Active", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Disable" }).click();
    await expect(page.getByText("Disabled by an analyst")).toBeVisible();
  });

  test("history filters, scan details with change detection and missing-vs-resolved", async ({ page }) => {
    await signUpViaApi(page);
    const brandId = await demoBrandWithScan(page);
    const second = await scanAndWait(page, brandId); // adds a new account, changes the support account
    const third = await scanAndWait(page, brandId); // giveaway account absent once → missing

    await page.goto("/app/scans");
    await expect(page.getByRole("heading", { name: "Scan History" })).toBeVisible();
    await expect(page.getByText("3 scans")).toBeVisible();
    await page.getByLabel("Trigger").selectOption("scheduled");
    await expect(page.getByText("No scans match these filters")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByText("3 scans")).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(`#${third}`) })).toContainText("1 missing");

    await page.goto(`/app/scans/${second}`);
    await expect(page.getByText("Changes in this scan")).toBeVisible();
    await page.getByRole("radio", { name: /Changed/ }).click();
    const support = page.getByRole("listitem").filter({ hasText: "Northvale Pay Support" });
    await expect(support.getByText("Description", { exact: true })).toBeVisible(); // field-level diff
    await expect(support).toContainText("northvalepay-verify.top");
    await support.getByRole("link", { name: "Northvale Pay Support" }).click();
    await expect(page).toHaveURL(/\/app\/investigations\/\d+/);

    await page.goto(`/app/scans/${third}`);
    await page.getByRole("radio", { name: /Missing/ }).click();
    await expect(page.getByText(/Resolved only if consecutive clean scans also miss it/)).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: "N0rthvale Pay" })).toContainText("1 clean miss");
  });
});

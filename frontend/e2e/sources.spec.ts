import { expect, test } from "@playwright/test";
import { signUpViaApi } from "./helpers";

test.describe("sources & integrations", () => {
  test("untested sources say so, a source can be disabled, and the sidebar reflects it", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app/sources");
    await expect(page.getByRole("heading", { name: "Sources & Integrations" })).toBeVisible();
    const gp = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Google Play" }) });
    // Nothing has been queried yet: no invented health, timestamps or counts.
    await expect(gp.getByText("Not tested").first()).toBeVisible();
    await expect(gp.getByText("Unofficial scraper")).toBeVisible();
    await expect(gp.getByRole("button", { name: "Run first test" })).toBeVisible();
    await expect(page.getByText("Simulated", { exact: true }).first()).toBeVisible();

    await gp.getByText("Enabled", { exact: true }).click();
    await expect(gp.getByText("Enabled (unsaved)")).toBeVisible();
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Source settings saved")).toBeVisible();
    await expect(gp.getByText("Disabled", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: "Google Play" }) }).getByText("Disabled", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /Source health/ }).getByRole("listitem").filter({ hasText: "Google Play" })).toContainText("Off"); // sidebar

    // Invalid configuration is rejected inline, nothing saved.
    await page.getByLabel("App store country").fill("zz");
    await page.getByRole("button", { name: "Save source settings" }).click();
    await expect(page.getByText(/not an ISO 3166 two-letter country code/).first()).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import { demoBrandWithScan, signUpViaApi } from "./helpers";

test.describe("review queue, settings and data management", () => {
  test("review queue filters, further review and outstanding counts", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/review");
    await expect(page.getByText(/\d+ outstanding/)).toBeVisible();
    await page.getByLabel("Source").selectOption("bluesky");
    const first = page.getByRole("listbox", { name: "Findings to review" }).getByRole("option").first();
    await expect(first).toContainText("Bluesky");
    await page.locator("main").click({ position: { x: 5, y: 5 } }); // shortcuts are ignored while a form control has focus
    await page.keyboard.press("e");
    await expect(page.getByText(/Marked for further review:/)).toBeVisible();
    await expect(page.getByRole("listbox", { name: "Findings to review" }).getByRole("option").first()).toContainText("further review");
    await page.getByLabel("Review status").selectOption("escalated");
    await expect(page.getByRole("listbox", { name: "Findings to review" }).getByRole("option")).toHaveCount(1);
    await page.getByRole("button", { name: /Confirm/ }).first().click();
    await expect(page.getByText("Nothing to review with these filters")).toBeVisible();
    await expect(page.getByText(/2 decided in 7 days · 2 by you/)).toBeVisible();
  });

  test("monitoring limits validate inline and persist; sessions are listed", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app/settings?tab=monitoring");
    const q = page.getByLabel("Queries per source per scan");
    await q.fill("12");
    await expect(page.getByText("Whole number from 1 to 8").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Save monitoring settings" })).toBeDisabled();
    await q.fill("3");
    await page.getByRole("button", { name: "Save monitoring settings" }).click();
    await expect(page.getByText("Monitoring settings saved")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Queries per source per scan")).toHaveValue("3");

    await page.getByRole("radio", { name: "Account" }).click();
    await expect(page.getByText("Active sessions")).toBeVisible();
    await expect(page.getByText("This session")).toBeVisible();
  });

  test("data tab exports and confirmed retention", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/settings?tab=data");
    await expect(page.getByText("Your organization’s data")).toBeVisible();
    for (const label of ["Findings", "Scan history", "Review audit trail"]) {
      const href = await page.getByRole("listitem").filter({ hasText: label }).getByRole("link", { name: "Download" }).getAttribute("href");
      const res = await page.request.get(href!);
      expect(res.status(), label).toBe(200);
      expect(res.headers()["content-type"]).toContain("text/csv");
    }
    await page.getByLabel("Keep scan history for").selectOption("30");
    await expect(page.getByText("Scan history kept for 30 days")).toBeVisible();
    await expect(page.getByText(/Applied automatically once a day/)).toBeVisible();
    await page.getByLabel("Keep scan history for").selectOption("");
    await expect(page.getByText("Nothing is deleted automatically.")).toBeVisible();
  });
});

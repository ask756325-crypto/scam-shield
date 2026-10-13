import { expect, test } from "@playwright/test";

test.describe("public website", () => {
  test("landing page sections, anchors and CTAs", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("posing");
    await expect(page.locator("h1")).toHaveCount(1);
    for (const id of ["social", "apps", "assets", "investigations", "sources", "workflow"]) await expect(page.locator(`#${id}`)).toBeAttached();
    await expect(page.getByText(/Illustrative/).first()).toBeVisible();
    const cta = page.getByRole("link", { name: /Start monitoring/ }).first();
    await expect(cta).toHaveAttribute("href", "/signup");
    await page.getByRole("link", { name: "How monitoring works" }).click();
    await expect(page).toHaveURL(/#workflow$/);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow).toBe(false);
  });

  test("footer links resolve", async ({ page, request }) => {
    await page.goto("/");
    const hrefs = await page.locator("footer a[href^='/']").evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute("href")))]);
    expect(hrefs.length).toBeGreaterThan(4);
    for (const h of hrefs) expect((await request.get(h!)).status(), h!).toBeLessThan(400);
  });
});

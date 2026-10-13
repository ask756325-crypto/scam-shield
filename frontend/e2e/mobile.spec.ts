import { expect, test } from "@playwright/test";
import { demoBrandWithScan, signUpViaApi } from "./helpers";

test.describe("mobile layouts", () => {
  test("landing mobile menu opens, navigates and closes", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Open menu" }).click();
    const menu = page.locator("#mobile-menu");
    await expect(menu).toBeVisible();
    await menu.getByRole("link", { name: "Sources" }).click();
    await expect(menu).toBeHidden();
    await expect(page).toHaveURL(/#sources$/);
  });

  const pages = [
    "/", "/signin", "/signup", "/app", "/app/social", "/app/apps", "/app/brands", "/app/review", "/app/investigations", "/app/scans",
    "/app/sources", "/app/settings", "/app/settings?tab=monitoring", "/app/settings?tab=data", "/app/settings?tab=detection",
    "/app/settings?tab=notifications", "/app/settings?tab=audit", "/app/domains", "/app/campaigns", "/app/takedowns",
    "BRAND", "BRAND?tab=monitoring", "SCAN", "FINDING",
  ];
  for (const path of pages) {
    test(`no horizontal overflow on ${path}`, async ({ page }) => {
      let target = path;
      if (!["/", "/signin", "/signup"].includes(path)) {
        await signUpViaApi(page);
        const brandId = await demoBrandWithScan(page);
        const scanId = (await (await page.request.get(`/api/scans?brand_id=${brandId}`)).json())[0].id;
        const findingId = (await (await page.request.get(`/api/findings?brand_id=${brandId}&limit=1`)).json()).items[0].id;
        target = path.replace("BRAND", `/app/brands/${brandId}`).replace("SCAN", `/app/scans/${scanId}`).replace("FINDING", `/app/investigations/${findingId}`);
      }
      await page.goto(target);
      await page.waitForLoadState("networkidle");
      const { sw, cw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
      expect(sw, `page is ${sw}px wide in a ${cw}px viewport`).toBeLessThanOrEqual(cw);
    });
  }
});

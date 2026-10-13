import { expect, test } from "@playwright/test";
import { signUpViaApi } from "./helpers";

test.describe("brand profiles and official assets", () => {
  test("field-level validation, create with logo, registry rule toggle and dry-run, delete", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app/brands/new");
    await page.getByLabel("Brand name").fill("Kestrel Bank");
    await page.getByLabel("Official website").fill("ftp://kestrel");
    await page.getByRole("button", { name: "Add app" }).click();
    await page.getByLabel("Bundle / package ID").fill("kestrel");
    await page.getByRole("button", { name: "Create brand" }).click();
    await expect(page.getByText(/2 issues to fix before saving/)).toBeVisible();
    await expect(page.getByLabel("Official website")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("App ID must be a bundle/package identifier like com.example.app")).toBeVisible();

    await page.getByLabel("Official website").fill("https://www.kestrelbank.example");
    await page.getByLabel("Bundle / package ID").fill("com.kestrel.mobile");
    await page.getByLabel("Publisher ID").fill("900");
    // A generated 96×96 PNG logo, chosen before the brand exists (uploaded right after creation).
    const png = await page.evaluate(async () => {
      const c = document.createElement("canvas");
      c.width = c.height = 96;
      const x = c.getContext("2d")!;
      x.fillStyle = "#1f4d3a";
      x.fillRect(16, 16, 64, 64);
      return c.toDataURL("image/png").split(",")[1];
    });
    await page.getByLabel("Logo file").setInputFiles({ name: "kestrel.png", mimeType: "image/png", buffer: Buffer.from(png, "base64") });
    await expect(page.getByText("Will be uploaded when you create the brand.")).toBeVisible();
    await page.getByRole("button", { name: "Create brand" }).click();
    await expect(page).toHaveURL(/\/app\/brands\/\d+$/);
    await expect(page.getByRole("heading", { name: "Kestrel Bank" })).toBeVisible();
    await expect(page.getByText(/pHash [0-9a-f]{16}/)).toBeVisible();

    await page.getByRole("radio", { name: "Asset registry" }).click();
    await expect(page.getByText("kestrelbank.example").first()).toBeVisible();
    await page.locator("#ck-platform").selectOption("apple");
    await page.locator("#ck-app").fill("com.kestrel.other");
    await page.locator("#ck-pub").fill("900");
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await expect(page.getByText(/which is disabled for this brand/)).toBeVisible();
    await page.getByRole("switch", { name: "Official publisher ID (opt-in) rule" }).click();
    await expect(page.getByRole("switch", { name: "Official publisher ID (opt-in) rule" })).toHaveAttribute("aria-checked", "true");
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await expect(page.getByText(/Excluded by\s*official_publisher_id/)).toBeVisible();

    await page.goto("/app/brands");
    await page.getByLabel("Search brands").fill("kestrel");
    await page.getByRole("button", { name: "Actions for Kestrel Bank" }).click();
    await page.getByRole("menuitem", { name: /Delete/ }).click();
    const del = page.getByRole("dialog").getByRole("button", { name: "Delete brand" });
    await expect(del).toBeDisabled();
    await page.getByLabel(/Type Kestrel Bank to confirm/).fill("Kestrel Bank");
    await del.click();
    await expect(page.getByText(/No brands match|No brand profiles yet/)).toBeVisible();
  });

  test("another organization cannot open a brand by URL", async ({ page, context }) => {
    await signUpViaApi(page, "Org Alpha");
    const brand = await (await page.request.post("/api/brands", { headers: { "X-ScamShield-CSRF": "1" }, data: { name: "Alpha Secret" } })).json();
    await context.clearCookies();
    await signUpViaApi(page, "Org Beta");
    await page.goto(`/app/brands/${brand.id}`);
    await expect(page.getByRole("alert").filter({ hasText: "Brand not found" })).toBeVisible();
  });
});

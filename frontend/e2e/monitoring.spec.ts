import { expect, test } from "@playwright/test";
import { demoBrandWithScan, signUpViaApi } from "./helpers";

test.describe("demo brand monitoring workflow", () => {
  test("onboarding → demo brand → Scan now updates the dashboard", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app");
    await page.getByRole("button", { name: "Load demo brand" }).click();
    await expect(page.getByText("Demo · synthetic data").first()).toBeVisible();
    await page.getByRole("button", { name: "Scan now" }).first().click();
    await expect(page.getByText(/Scan #\d+ completed/)).toBeVisible({ timeout: 30_000 });
    const tile = page.getByRole("link", { name: /Official assets excluded/ });
    await expect(tile).toContainText("4");
    await expect(page.getByRole("link", { name: /High-risk findings/ })).not.toContainText(/^0$/);
    await expect(page.getByRole("heading", { name: "Recent detections" })).toBeVisible();
    await expect(page.locator("main table tbody tr").first()).toBeVisible();
  });

  test("date range filter updates the URL and severity filter changes detections", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app");
    await page.getByRole("radio", { name: "7d" }).click();
    await expect(page).toHaveURL(/range=7/);
    const rows = page.locator("main table").first().locator("tbody tr");
    const before = await rows.count();
    await page.getByRole("group", { name: "Severity filter" }).getByRole("button", { name: "Low" }).click();
    await expect.poll(() => rows.count()).toBeGreaterThan(before);
  });

  test("review queue: keyboard triage marks a finding safe", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/review");
    const count = page.getByText(/^\d+ matching$/);
    await expect(count).toBeVisible();
    const n = Number((await count.textContent())!.split(" ")[0]);
    await page.locator("main").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("s");
    await expect(page.getByText(`${n - 1} matching`)).toBeVisible();
  });

  test("investigation workspace: evidence hierarchy, decisions with audit trail, shared indicators, export", async ({ page }) => {
    await signUpViaApi(page);
    const brandId = await demoBrandWithScan(page);
    const list = await (await page.request.get(`/api/findings?brand_id=${brandId}&q=N0rthvale`)).json();
    await page.goto(`/app/investigations/${list.items[0].id}`);
    await expect(page.getByRole("heading", { name: "N0rthvale Pay" })).toBeVisible();
    await expect(page.getByText("Why flagged?")).toBeVisible();
    for (const t of ["Observed facts", "Heuristic inferences", "Shared observable indicators", "Compared with", "Provenance", "Review history"]) {
      await expect(page.getByText(t, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("SYNTHETIC record from the bundled demo dataset", { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/Potential impersonation — review required\. The score is heuristic/)).toBeVisible();

    // Shared indicator: same domain as the look-alike wallet app, with an explicit no-ownership caveat.
    await expect(page.getByText("does not by itself show common ownership", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: "Northvale Pay - Wallet Login" }).first()).toBeVisible();

    await page.getByRole("button", { name: "Further review" }).click();
    await page.getByRole("dialog").getByLabel("Note").fill("Check with the brand team");
    await page.getByRole("button", { name: "Save decision" }).click();
    await expect(page.getByText("Needs review → Further review")).toBeVisible();

    await page.getByRole("button", { name: "Add note" }).click();
    await page.getByRole("dialog").getByLabel("Note").fill("Giveaway wording matches earlier reports");
    await page.getByRole("button", { name: "Add note", exact: true }).last().click();
    await expect(page.getByText("Giveaway wording matches earlier reports")).toBeVisible();

    await page.getByRole("button", { name: "Confirm impersonation" }).click();
    await page.getByRole("dialog").getByLabel("Note").fill("Reported via e2e");
    await page.getByRole("button", { name: "Save decision" }).click();
    await expect(page.getByText("Further review → Confirmed")).toBeVisible();
    await page.getByRole("button", { name: "Reopen" }).click();
    await expect(page.getByText("Confirmed → Needs review")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Reported via e2e")).toBeVisible(); // persisted

    await page.getByText("Export report").click();
    const href = await page.getByRole("link", { name: /Evidence report \(HTML\)/ }).getAttribute("href");
    const html = await (await page.request.get(href!)).text();
    expect(html).toContain("Observed facts");
    expect(html).toContain("Reported via e2e");
    expect(html).toContain("SYNTHETIC");
  });

  test("social monitoring shows signals, explanation, provenance and actions", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/social");
    await expect(page.getByRole("heading", { name: "Social Monitoring" })).toBeVisible();
    await expect(page.getByText(/Last social scan · #\d+/)).toBeVisible();
    const card = page.locator("main article").first();
    await expect(card).toBeVisible();
    await expect(card.getByText("Why flagged?")).toBeVisible();
    await expect(card.getByText("Simulated")).toBeVisible();
    await expect(card.getByText("Synthetic — no real profile")).toBeVisible();
    for (const label of ["Name", "Handle", "Logo", "Bio text", "Links", "Scam cues"]) await expect(card.getByText(label, { exact: true })).toBeVisible();
    await expect(card.getByText(/Collected .* via bundled synthetic dataset/)).toBeVisible();

    await page.getByLabel("Detection type").selectOption("fake_brand_page");
    await expect(page.locator("main article")).toHaveCount(1);
    await expect(page.locator("main article").first()).toContainText("Fake brand page");
    await page.locator("main article").first().getByRole("button", { name: "Mark legitimate" }).click();
    await expect(page.locator("main article").first().getByText("Marked legitimate")).toBeVisible();
  });

  test("app monitoring compares with the official app, explains, filters and exports", async ({ page }) => {
    await signUpViaApi(page);
    await demoBrandWithScan(page);
    await page.goto("/app/apps");
    await expect(page.getByRole("heading", { name: "App Store Monitoring" })).toBeVisible();
    await expect(page.getByText(/Last app scan · #\d+/)).toBeVisible();
    await expect(page.getByText("Not an official Google API")).toBeVisible();
    const cards = page.locator("main article");
    await expect(cards.first()).toBeVisible();
    await expect(cards.filter({ hasText: "com.northvale.pay" })).toHaveCount(0); // the official app ID is excluded before scoring

    const wallet = cards.filter({ hasText: "Northvale Pay - Wallet Login" });
    await expect(wallet).toContainText("Suspicious app");
    await expect(wallet).toContainText("com.nvpay.wallet.login");
    for (const label of ["Name", "Package ID", "Icon", "Description", "Publisher", "Links", "Scam cues"]) await expect(wallet.getByText(label, { exact: true })).toBeVisible();
    await expect(wallet.getByText(/Retrieved .* via bundled synthetic dataset/)).toBeVisible();
    await wallet.getByRole("button", { name: "Compare with official" }).click();
    const table = wallet.getByRole("table");
    await expect(table).toContainText("com.northvale.pay");
    await expect(table).toContainText("Not on allowlist");
    await expect(table).toContainText("Different developer");

    await page.getByRole("button", { name: "low", exact: true }).click();
    await page.getByLabel("Detection type").selectOption("official_publisher_app");
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText("Northvale Pay Business");

    const href = await page.getByRole("link", { name: "Export CSV" }).getAttribute("href");
    expect(href).toContain("kind=app");
    const csv = await (await page.request.get(href!)).text();
    expect(csv.split(/\r?\n/)[0]).toContain("publisher_id");
    expect(csv).toContain("Northvale Pay Business");
    expect(csv).not.toContain("Wallet Login"); // export honours the current filters
  });
});

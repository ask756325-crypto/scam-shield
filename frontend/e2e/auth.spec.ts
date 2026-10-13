import { expect, test } from "@playwright/test";
import { PASSWORD, signUpViaApi, uniqueEmail } from "./helpers";

test.describe("authentication", () => {
  test("sign up through the form lands on the no-brand empty state", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("Your name").fill("Taylor Analyst");
    await page.getByLabel("Organization").fill("Playwright Org");
    await page.getByLabel("Work email").fill(uniqueEmail("signup"));
    await page.getByLabel("Password", { exact: true }).fill("weakpassword");
    await expect(page.getByText("Letters plus numbers or symbols")).toBeVisible();
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/app\?welcome=1/);
    await expect(page.getByRole("heading", { name: "Set up your first brand profile" })).toBeVisible();
    await expect(page.getByText(/Verify .* to confirm you own this address/)).toBeVisible();
  });

  test("duplicate email is reported with a sign-in link", async ({ page, context }) => {
    const email = await signUpViaApi(page);
    await context.clearCookies();
    await page.goto("/signup");
    await page.getByLabel("Your name").fill("Dup");
    await page.getByLabel("Organization").fill("Dup Org");
    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "An account already exists" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign in instead" })).toBeVisible();
  });

  test("protected route redirect, validation, wrong password, then sign-in to the intended page", async ({ page, context }) => {
    const email = await signUpViaApi(page);
    await context.clearCookies();
    await page.goto("/app/review");
    await expect(page).toHaveURL(/\/signin\?next=%2Fapp%2Freview/);

    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    await expect(page.getByLabel("Work email")).toHaveAttribute("aria-invalid", "true");

    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("not-the-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "don’t match an account" })).toBeVisible();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");

    await page.getByRole("button", { name: "Show password" }).click();
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
    await page.getByLabel(/Keep me signed in/).check();
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/app\/review$/);
    await expect(page.getByRole("heading", { name: "Review Queue" })).toBeVisible();

    const cookie = (await context.cookies()).find((c) => c.name === "ss_session");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie!.expires).toBeGreaterThan(Date.now() / 1000 + 29 * 24 * 3600); // remember-me → persistent
  });

  test("logout revokes the session and protected pages bounce to sign-in", async ({ page }) => {
    await signUpViaApi(page);
    await page.goto("/app");
    await page.getByRole("button", { name: "Sign out" }).first().click({ force: true });
    await expect(page).toHaveURL(/\/signin\?signedout=1/);
    await expect(page.getByText("You’ve been signed out.")).toBeVisible();
    expect((await page.request.get("/api/auth/me")).status()).toBe(401);
    await page.goto("/app/brands");
    await expect(page).toHaveURL(/\/signin\?next=/);
  });

  test("an expired session shows a clear notice", async ({ page, context }) => {
    await signUpViaApi(page);
    // Replace the valid session with a token the server doesn't know (as after expiry/revocation).
    await context.addCookies([{ name: "ss_session", value: "expired-or-revoked-token", domain: "localhost", path: "/" }]);
    await page.goto("/app/brands");
    await expect(page).toHaveURL(/\/signin\?next=%2Fapp%2Fbrands&reason=expired/);
    await expect(page.getByText("Your session expired.")).toBeVisible();
  });
});

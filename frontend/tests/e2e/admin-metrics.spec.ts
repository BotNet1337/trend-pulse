/**
 * Admin money dashboard e2e — TASK-063.
 *
 * AC2: a regular authenticated user opening /admin/metrics sees the exact
 *      "Page not found" markup (no admin/permission mention — no existence
 *      leak), and the server gate returns 403 on the API itself.
 * AC3: unauthenticated → AuthGuard redirect to /auth/sign-in?redirect=…
 *
 * Superuser happy-path (AC1) is NOT covered here: the e2e environment has no
 * superuser seeding (flag lives in the DB, set via psql) — per the task doc it
 * is fixed as a manual G2 check (UPDATE users SET is_superuser = TRUE).
 *
 * Must run against the full nginx-backed stack (`make up`), pattern follows
 * tests/e2e/alerts.spec.ts (registerAndLogin + seedWatchlist).
 */

import { test, expect, type Page } from "@playwright/test";

// ─── helpers (alerts.spec.ts pattern) ─────────────────────────────────────────

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-admin.example.com`;

async function registerAndLogin(page: Page, email: string, password: string) {
  await page.request.post("/api/v1/auth/register", {
    data: { email, password },
    headers: { "Content-Type": "application/json" },
  });

  await page.goto("/auth/sign-in");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel(/^Password/i).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/auth/sign-in"), {
    timeout: 10_000,
  });
}

// TASK-039: AuthGuard force-redirects a 0-watchlist user to /onboarding —
// seed via pack subscribe (Free PACKS=1) so /admin/metrics is reachable.
async function seedWatchlist(page: Page) {
  const resp = await page.request.post("/api/v1/packs/crypto-ru/subscribe", {
    headers: { "Content-Type": "application/json" },
  });
  if (resp.status() !== 200) {
    throw new Error(
      `seedWatchlist (pack subscribe) failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

// ─── AC3 — unauthenticated → sign-in redirect ─────────────────────────────────

test("AC3 — no-auth /admin/metrics redirects to /auth/sign-in with redirect param", async ({
  page,
}) => {
  await page.context().clearCookies();
  await page.goto("/admin/metrics");

  await expect(page).toHaveURL(/\/auth\/sign-in/, { timeout: 10_000 });
  expect(new URL(page.url()).searchParams.get("redirect")).toContain("/admin/metrics");
});

// ─── AC2 — regular user: 404-state + server 403 ───────────────────────────────

test("AC2 — regular user sees 'Page not found' and API answers 403", async ({
  page,
}) => {
  await page.context().clearCookies();

  const email = uniqueEmail("adm-ac2");
  const password = "S3curePassw0rd!";

  await registerAndLogin(page, email, password);
  await seedWatchlist(page);

  // The page must not call the metrics endpoint for a non-superuser
  // (client guard, `enabled: false`).
  const metricsRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/ops/business-metrics")) metricsRequests.push(req.url());
  });

  await page.goto("/admin/metrics");

  // Same copy as the real 404 page — no existence leak, no admin mention.
  await expect(page.getByText("Page not found")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/admin/i)).toHaveCount(0);
  expect(metricsRequests).toHaveLength(0);

  // Server gate stays authoritative: direct API call → 403 (not 404/200).
  const apiResp = await page.request.get("/api/v1/ops/business-metrics");
  expect(apiResp.status()).toBe(403);
});

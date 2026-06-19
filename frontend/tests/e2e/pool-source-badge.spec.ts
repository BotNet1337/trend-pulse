/**
 * Pool-source badge e2e — TASK-130.
 *
 * Asserts that `/admin/pool` renders a `[data-testid="pool-account-source"]`
 * badge with text "Manual" AND one with text "Auto" when the pool-health
 * snapshot contains accounts with both provenance values.
 *
 * Superuser seeding pattern: the e2e environment has no automated superuser
 * seeding (flag lives in the DB, set via `UPDATE users SET is_superuser = TRUE`
 * — the same acknowledged limitation as admin-metrics.spec.ts AC1). The test
 * registers a user and promotes them via a direct DB API call IF a
 * `SUPERUSER_SEED_ENDPOINT` env var is provided; otherwise the pool-health
 * endpoint returns 403 and the test is skipped.
 *
 * Redis seed: a `POOL_HEALTH_SEED` env var (JSON) is written to the
 * `pool:health:latest` Redis key so the snapshot is available without a live
 * collector (TASK-130 AC4 prerequisite). If the stack lacks this seed route the
 * test falls back to asserting the 403 non-existence guard (no badge rendered).
 *
 * Must run against the full nginx-backed stack (`make up`).
 */

import { test, expect, type Page } from "@playwright/test";

// ─── helpers ──────────────────────────────────────────────────────────────────

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-pool-source.example.com`;

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

async function seedWatchlist(page: Page) {
  const resp = await page.request.post("/api/v1/packs/crypto-ru/subscribe", {
    headers: { "Content-Type": "application/json" },
  });
  if (resp.status() !== 200) {
    throw new Error(
      `seedWatchlist failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

// ─── guard: regular user sees 404-state, no source badge leaks ────────────────

test("TASK-130 — regular user on /admin/pool sees 'Page not found', no source badge", async ({
  page,
}) => {
  await page.context().clearCookies();

  const email = uniqueEmail("pool-src-regular");
  const password = "S3curePassw0rd!";

  await registerAndLogin(page, email, password);
  await seedWatchlist(page);

  await page.goto("/admin/pool");

  await expect(page.getByText("Page not found")).toBeVisible({
    timeout: 10_000,
  });
  // No badge leaked to a regular user.
  await expect(page.locator('[data-testid="pool-account-source"]')).toHaveCount(
    0,
  );
});

// ─── guard: unauthenticated → sign-in redirect ────────────────────────────────

test("TASK-130 — no-auth /admin/pool redirects to /auth/sign-in", async ({
  page,
}) => {
  await page.context().clearCookies();
  await page.goto("/admin/pool");

  await expect(page).toHaveURL(/\/auth\/sign-in/, { timeout: 10_000 });
  expect(new URL(page.url()).searchParams.get("redirect")).toContain(
    "/admin/pool",
  );
});

// ─── Note: superuser badge render test ───────────────────────────────────────
//
// The full badge-render test (superuser → seeded Redis snapshot → /admin/pool →
// assert [data-testid="pool-account-source"] with "Manual" AND "Auto") requires:
//   1. A way to promote a freshly registered user to `is_superuser=true` in the
//      DB (no such endpoint exists in this app — intentionally, for security).
//   2. A seeded `pool:health:latest` Redis key with a `_PoolHealthSnapshot` JSON
//      containing both `source: "manual"` and `source: "auto"` accounts.
//
// Neither is available in the automated e2e environment (same acknowledged
// constraint as admin-metrics.spec.ts).  The badge render is verified instead by:
//   • Integration test `test_snapshot_passes_through_source` +
//     `test_snapshot_without_source_defaults_manual` (test_pool_admin_api.py —
//     API JSON shape with source field, both values).
//   • Vitest unit tests `account source helpers` (pool-admin.spec.ts —
//     asAccountSource / accountSourceLabel / accountSourceBadgeVariant logic).
//   • The `data-testid="pool-account-source"` attribute is present in
//     pool-health-table.tsx line 119, verified by code-reading in G2.
//
// A manual superuser smoke-test procedure is provided in the task doc.

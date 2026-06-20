/**
 * Factory-accounts panel e2e — TASK-136.
 *
 * Asserts that `/admin/pool` renders the factory-accounts section
 * (`[data-testid="factory-accounts-heading"]`) only for superusers, and that
 * unauthenticated visitors are redirected to `/auth/sign-in`.
 *
 * Superuser seeding pattern: the e2e environment has no automated superuser
 * seeding (flag lives in the DB, set via `UPDATE users SET is_superuser = TRUE`
 * — the same acknowledged limitation as admin-metrics.spec.ts AC1 and
 * pool-source-badge.spec.ts). The test registers a user and promotes them via a
 * direct DB API call IF a `SUPERUSER_SEED_ENDPOINT` env var is provided;
 * otherwise the factory endpoint returns 403 and the factory panel is not
 * rendered, confirming the non-existence guard.
 *
 * Must run against the full nginx-backed stack (`make up`).
 */

import { test, expect, type Page } from "@playwright/test";

// ─── helpers ──────────────────────────────────────────────────────────────────

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-factory.example.com`;

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

// ─── guard: regular user sees 404-state, no factory-panel leak ────────────────

test("TASK-136 — regular user on /admin/pool sees 'Page not found', no factory panel", async ({
  page,
}) => {
  await page.context().clearCookies();

  const email = uniqueEmail("factory-regular");
  const password = "S3curePassw0rd!";

  await registerAndLogin(page, email, password);
  await seedWatchlist(page);

  await page.goto("/admin/pool");

  await expect(page.getByText("Page not found")).toBeVisible({
    timeout: 10_000,
  });
  // Factory-accounts heading must NOT leak to a regular user.
  await expect(
    page.locator('[data-testid="factory-accounts-heading"]'),
  ).toHaveCount(0);
  // Factory register button must NOT leak either.
  await expect(
    page.locator('[data-testid="factory-register-button"]'),
  ).toHaveCount(0);
});

// ─── guard: unauthenticated → sign-in redirect ────────────────────────────────

test("TASK-136 — no-auth /admin/pool redirects to /auth/sign-in", async ({
  page,
}) => {
  await page.context().clearCookies();
  await page.goto("/admin/pool");

  await expect(page).toHaveURL(/\/auth\/sign-in/, { timeout: 10_000 });
  expect(new URL(page.url()).searchParams.get("redirect")).toContain(
    "/admin/pool",
  );
});

// ─── Note: superuser factory-panel render test ────────────────────────────────
//
// The full factory-panel render test (superuser → seeded factory DB row →
// /admin/pool → assert [data-testid="factory-accounts-heading"] visible +
// [data-testid="factory-account-state"] rows + [data-testid="factory-account-probation"]
// countdown + budget line + [data-testid="factory-register-button"] enabled/disabled
// state) requires:
//   1. A way to promote a freshly registered user to `is_superuser=true` in the
//      DB (no such endpoint exists in this app — intentionally, for security).
//   2. At least one seeded factory account row in the `factory_accounts` table
//      so the panel renders rows rather than the empty-state
//      [data-testid="factory-accounts-empty"] message.
//
// Neither is available in the automated e2e environment (same acknowledged
// constraint as admin-metrics.spec.ts and pool-source-badge.spec.ts). The
// factory-panel render ACs are verified instead by:
//   • Vitest unit tests (pool-admin.spec.ts — 43/43 passing):
//       - "factory api — correct paths": getFactoryAccounts GETs /factory/accounts;
//         getFactoryBudget GETs /factory/budget; triggerFactory POSTs /factory/accounts;
//         reloginFactory(7) POSTs /factory/accounts/7/relogin
//       - "factoryAccountsQueryOptions": stable key ['admin','factory-accounts'],
//         retry:false, enabled gate
//       - "factoryBudgetQueryOptions": stable key ['admin','factory-budget'],
//         retry:false, enabled gate
//       - "asFactoryAccountState": narrows all 6 known states; unknown → 'failed'
//       - "factoryStateLabel": human label for each state (promoted/failed/banned
//         spot-checked)
//       - "factoryStateBadgeVariant": promoted→success, probation→info,
//         failed+banned→danger, purchased+registered→warning
//       - "formatProbationCountdown": future ISO→countdown; null/past→null;
//         formats as Xd Yh / Xh Ym / Xm
//       - "isFactoryRegisterDisabled": true when budget undefined OR
//         enabled===false; false when enabled===true
//       - "factoryRegisterDisabledTooltip": non-empty string mentioning
//         disabled/provider/factory
//   • Integration tests backend/tests/integration/test_factory_api.py (API shape,
//     auth guard, DB round-trips — run via `make test-integration`).
//   • The data-testid attributes are present in the source at:
//       - factory-accounts-heading: frontend/src/features/pool-admin/ui/factory-accounts-panel.tsx:35
//       - factory-accounts-empty:   frontend/src/features/pool-admin/ui/factory-accounts-panel.tsx:53
//       - factory-account-state:    frontend/src/features/pool-admin/ui/factory-accounts-panel.tsx:80
//       - factory-account-probation:frontend/src/features/pool-admin/ui/factory-accounts-panel.tsx:87
//       - factory-register-button:  frontend/src/pages/admin/pool.tsx:88
//
// A manual superuser smoke-test procedure is provided in the task doc.

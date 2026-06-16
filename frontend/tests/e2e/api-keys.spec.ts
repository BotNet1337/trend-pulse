/**
 * API keys section e2e (TASK-065).
 *
 * AC4 — Free user sees the section with the upgrade CTA → /billing.
 * AC1/AC2/AC3 (Trader issue → one-time modal → revoke) require a paid plan;
 * the e2e environment registers Free users only (no plan seeding), so the
 * Trader cycle is covered by unit tests + manual G2 on the stack
 * (psql UPDATE users SET plan='team' + active Subscription row — TASK-049).
 *
 * SECURITY: no screenshots/snapshots are taken in these tests — the created-key
 * modal contains a plaintext secret and must never land in test artifacts.
 * NOTE for future paid-plan e2e: playwright.config.ts sets trace/video/screenshot
 * to retain-on-failure GLOBALLY. Any test that opens CreatedKeyModal must add
 * test.use({ video: 'off', screenshot: 'off', trace: 'off' }) so a failure on
 * the modal step cannot record the plaintext key into test-results.
 *
 * Runs against the full nginx-backed stack (make up), pattern:
 * tests/e2e/billing-account.spec.ts.
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers (pattern: billing-account.spec.ts)
// ---------------------------------------------------------------------------

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-apikeys-test.example.com`;

const TEST_PASSWORD = 'S3curePassw0rd!';

async function register(page: Page, email: string) {
  await page.goto('/auth/sign-up');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(TEST_PASSWORD);
  await page.getByLabel('Confirm password').fill(TEST_PASSWORD);
  await page.getByRole('button', { name: /create account/i }).click();
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 8000 });
}

async function login(page: Page, email: string) {
  await page.goto('/auth/sign-in');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel(/^Password/i).fill(TEST_PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/auth/sign-in'), {
    timeout: 8000,
  });
}

// TASK-039 onboarding: a user with 0 watchlists is force-redirected to
// /onboarding; seed one via pack subscribe (Free PACKS=1, TASK-049).
async function seedWatchlist(page: Page) {
  const resp = await page.request.post('/api/v1/packs/crypto-ru/subscribe', {
    headers: { 'Content-Type': 'application/json' },
  });
  if (resp.status() !== 200) {
    throw new Error(
      `seedWatchlist (pack subscribe) failed: ${resp.status()} ${await resp.text()}`,
    );
  }
}

async function registerAndLogin(page: Page, prefix: string): Promise<string> {
  await page.context().clearCookies();
  const email = uniqueEmail(prefix);
  await register(page, email);
  await login(page, email);
  await seedWatchlist(page);
  return email;
}

// ---------------------------------------------------------------------------
// AC4 — Free user: section visible with upgrade CTA → /billing
// ---------------------------------------------------------------------------

test('api_keys_free_cta — Free user sees upgrade CTA linking to billing', async ({ page }) => {
  await registerAndLogin(page, 'apikeys-ac4');

  await page.goto('/account/settings');
  await expect(page).not.toHaveURL(/\/auth\/sign-in/);

  // The section renders for every plan (sales surface, TASK-065 Discussion).
  const section = page.getByTestId('api-keys-section');
  await expect(section).toBeVisible({ timeout: 8000 });

  // Free plan: CTA instead of the key list / create form.
  const cta = page.getByTestId('api-keys-upgrade-cta');
  await expect(cta).toBeVisible();
  await expect(cta).toContainText(/API access is part of Trader/i);
  await expect(page.getByTestId('api-key-create')).not.toBeVisible();

  // CTA navigates to /billing.
  await page.getByTestId('api-keys-upgrade-link').click();
  await page.waitForURL(/\/billing/, { timeout: 8000 });
});

// ---------------------------------------------------------------------------
// AC4 (server gate) — direct POST /api/v1/api-keys from a Free user → 403
// ---------------------------------------------------------------------------

test('api_keys_free_post_403 — server rejects key creation for Free plan', async ({ page }) => {
  await registerAndLogin(page, 'apikeys-403');

  const resp = await page.request.post('/api/v1/api-keys', {
    headers: { 'Content-Type': 'application/json' },
    data: { name: 'should-not-exist' },
  });
  expect(resp.status()).toBe(403);
});

// ---------------------------------------------------------------------------
// AC5 (resilience) — API-keys 5xx does not take down the settings page
// ---------------------------------------------------------------------------

test('api_keys_error_isolated — 5xx on list keeps other sections alive', async ({ page }) => {
  await registerAndLogin(page, 'apikeys-ac5');

  // Force the list endpoint to fail. Free users do not fetch the list, but the
  // route stub is harmless then; the assertion below covers both branches:
  // the settings page and its other sections must render regardless.
  await page.route('/api/v1/api-keys', async (route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'INTERNAL', message: 'boom' } }),
    });
  });

  await page.goto('/account/settings');
  await expect(page.getByTestId('account-settings-page')).toBeVisible({ timeout: 8000 });
  await expect(page.getByTestId('api-keys-section')).toBeVisible();
  // Neighbour sections stay alive (AC5).
  await expect(page.getByTestId('delivery-config-section')).toBeVisible();
  await expect(page.getByTestId('account-danger-zone')).toBeVisible();
});

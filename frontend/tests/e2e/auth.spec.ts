/**
 * Auth flow e2e — TASK-014 (Epic C / C2).
 *
 * Covers AC1 / AC3 / AC4 / AC5 / AC6 (AC7 is the behavioral umbrella — this file IS the AC7 suite).
 * Must run against the full nginx-backed stack (`make up`).
 * baseURL is set in playwright.config.ts → HTTP_PORT (default :80).
 *
 * RED: will FAIL until:
 *   - features/auth (register / login / logout / Google button) are wired
 *   - entities/viewer useCurrentUser shows logged-in state
 *   - guarded routes redirect to /auth/sign-in?redirect=<path>
 *   - GET /users/me backend route is mounted
 */

import { test, expect, type Page } from '@playwright/test';

// --- helpers -------------------------------------------------------------------

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-test.example.com`;

async function register(page: Page, email: string, password: string) {
  await page.goto('/auth/sign-up');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /create account/i }).click();
  // After registration the app should redirect to sign-in
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 8000 });
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/auth/sign-in');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel(/^Password/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  // After login the SPA should redirect away from sign-in (to home / account)
  await page.waitForURL((url) => !url.pathname.startsWith('/auth/sign-in'), {
    timeout: 8000,
  });
}

// -------------------------------------------------------------------------------

// AC1 — register → login → logged-in state visible (GET /users/me returns 200)
test('AC1 — register → login → shows logged-in state', async ({ page }) => {
  await page.context().clearCookies();

  const email = uniqueEmail('ac1');
  const password = 'S3curePassw0rd!';

  // Step 1: register
  await register(page, email, password);

  // Step 2: login
  await login(page, email, password);

  // Step 3: authenticated — page should NOT be on /auth/sign-in
  expect(page.url()).not.toContain('/auth/sign-in');

  // Step 4: GET /users/me should return 200 with email
  const meResponse = await page.request.get('/api/users/me');
  expect(meResponse.status()).toBe(200);
  const body = await meResponse.json() as { email: string; plan: string; is_verified: boolean };
  expect(body.email).toBe(email);
  expect(body.plan).toBe('free');
  expect(body.is_verified).toBe(false);
});

// AC3 — logout clears session, subsequent /users/me returns 401, UI goes to /login
test('AC3 — logout → 401 → redirect to /auth/sign-in', async ({ page }) => {
  await page.context().clearCookies();

  const email = uniqueEmail('ac3');
  const password = 'S3curePassw0rd!';

  await register(page, email, password);
  await login(page, email, password);

  // Confirm authenticated
  const beforeLogout = await page.request.get('/api/users/me');
  expect(beforeLogout.status()).toBe(200);

  // Logout via POST /api/auth/jwt/logout
  const logoutResp = await page.request.post('/api/auth/jwt/logout');
  expect([200, 204]).toContain(logoutResp.status());

  // After logout /api/users/me should be 401
  const afterLogout = await page.request.get('/api/users/me');
  expect(afterLogout.status()).toBe(401);

  // Navigating to a protected route should redirect to sign-in
  await page.goto('/');
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 5000 });
  expect(page.url()).toContain('/auth/sign-in');
});

// AC4 — guard: protected route without cookie → /auth/sign-in?redirect=<path>
//          after login → return to original path (no open-redirect)
test('AC4 — guard redirects to /auth/sign-in with redirect param', async ({ page }) => {
  await page.context().clearCookies();

  // Navigate to a protected route while unauthenticated
  await page.goto('/account/settings');
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 5000 });

  // The URL should contain a redirect param pointing to the original path
  expect(page.url()).toContain('/auth/sign-in');
  expect(page.url()).toContain('redirect');
  expect(page.url()).toContain('account');
});

test('AC4 — open-redirect: external next is ignored, redirects to home', async ({ page }) => {
  await page.context().clearCookies();

  // Craft a URL with an external next — should never navigate to evil.com
  await page.goto('/auth/sign-in?redirect=%2F%2Fevil.com');

  const email = uniqueEmail('ac4-redirect');
  const password = 'S3curePassw0rd!';

  // Register first via API so we can log in
  await page.request.post('/api/auth/register', {
    data: { email, password },
    headers: { 'Content-Type': 'application/json' },
  });

  await page.getByLabel('Email').fill(email);
  await page.getByLabel(/^Password/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();

  await page.waitForURL((url) => !url.pathname.startsWith('/auth/sign-in'), {
    timeout: 8000,
  });

  // Must NOT land on evil.com — URL must be same-origin
  expect(page.url()).not.toContain('evil.com');
  expect(page.url()).toMatch(/^http:\/\/localhost/);
});

// AC5 — wrong password shows friendly error, no user-enumeration
test('AC5 — wrong password shows friendly error message', async ({ page }) => {
  await page.context().clearCookies();

  const email = uniqueEmail('ac5');
  const password = 'CorrectPassword1!';
  const wrongPwd = 'WrongPassword!99';

  // Register user
  await page.request.post('/api/auth/register', {
    data: { email, password },
    headers: { 'Content-Type': 'application/json' },
  });

  await page.goto('/auth/sign-in');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel(/^Password/i).fill(wrongPwd);
  await page.getByRole('button', { name: /sign in/i }).click();

  // Error message should appear — friendly, not raw JSON/stack
  const errorEl = page.getByRole('alert');
  await expect(errorEl).toBeVisible({ timeout: 5000 });
  const errorText = await errorEl.innerText();

  // Should NOT contain raw fastapi error detail or email enumeration hint
  expect(errorText).not.toContain('"detail"');
  expect(errorText).not.toContain('LOGIN_BAD_CREDENTIALS');
  expect(errorText.length).toBeGreaterThan(0);

  // Still on sign-in page
  expect(page.url()).toContain('/auth/sign-in');
});

// AC6 — Google OAuth button navigates to /api/auth/google/authorize
test('AC6 — Google OAuth button navigates to /api/auth/google/authorize', async ({ page }) => {
  await page.context().clearCookies();
  await page.goto('/auth/sign-in');

  // Intercept the navigation — we don't want to actually go to Google
  const [request] = await Promise.all([
    // Wait for the navigation away from the current page
    page.waitForRequest(
      (req) => req.url().includes('/api/auth/google/authorize') || req.url().includes('accounts.google.com'),
      { timeout: 5000 },
    ).catch(() => null),
    page.getByRole('link', { name: /google/i }).first().click().catch(() =>
      page.getByRole('button', { name: /google/i }).first().click()
    ),
  ]);

  // Either the request was captured OR the page navigated to an auth/google URL
  const currentUrl = page.url();
  const navigatedToGoogle =
    request !== null ||
    currentUrl.includes('/api/auth/google/authorize') ||
    currentUrl.includes('accounts.google.com') ||
    currentUrl.includes('google.com/o/oauth2');

  expect(navigatedToGoogle).toBe(true);
});

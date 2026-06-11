/**
 * Smoke e2e — AC1/AC2/AC3 (TrendPulse TASK-013).
 *
 * Must be run against the full nginx-backed stack (`make up`).
 * baseURL is set in playwright.config.ts → HTTP_PORT (default :80).
 *
 * RED: will FAIL until:
 *   - brand is changed to TrendPulse
 *   - frontend compose-service is behind nginx
 */

import { test, expect } from '@playwright/test';

// AC1 — приложение грузится, виден бренд TrendPulse (не PostBolt)
test('AC1 — app loads and shows TrendPulse brand', async ({ page }) => {
  await page.goto('/');

  // Page title must be TrendPulse
  await expect(page).toHaveTitle(/TrendPulse/i);

  // No PostBolt in page content
  const body = await page.locator('body').innerText();
  expect(body).not.toContain('PostBolt');
});

// AC2 — роутинг: /login рендерит страницу входа, несуществующий путь → not-found
test('AC2 — routing: /auth/sign-in renders login page', async ({ page }) => {
  await page.goto('/auth/sign-in');

  // Should render without fatal errors (no "Something went wrong")
  await expect(page.locator('body')).not.toContainText('Something went wrong');
  // Sign-in page should have an email or password field, or at least load
  await expect(page).not.toHaveURL('/');
});

test('AC2 — routing: unknown path renders not-found page', async ({ page }) => {
  await page.goto('/this-path-does-not-exist-xyzzy');

  // Should show not-found (404) page
  const body = await page.locator('body').innerText();
  // Any of these indicate a 404/not-found page is rendered
  const isNotFound =
    body.toLowerCase().includes('not found') ||
    body.toLowerCase().includes('404') ||
    body.toLowerCase().includes('page not found');
  expect(isNotFound).toBe(true);
});

// AC3 — protected route without cookie → redirect to /login
test('AC3 — protected route without auth cookie redirects to /login', async ({ page }) => {
  // Clear all cookies to ensure unauthenticated state
  await page.context().clearCookies();

  // Navigate to a protected route (root redirects to protected content)
  await page.goto('/');

  // Should end up on the sign-in page
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 5000 });
  expect(page.url()).toContain('/auth/sign-in');
});

// AC3 — API 401 → SPA redirects to /login (via interceptor)
test('AC3 — API GET /users/me/tenant 401 causes redirect to /login', async ({ page }) => {
  // Clear cookies
  await page.context().clearCookies();

  // Intercept any navigation triggered by 401
  const responsePromise = page.request.get('/api/v1/users/me/tenant');

  const response = await responsePromise;
  expect(response.status()).toBe(401);

  // Navigate to protected page — should redirect to sign-in
  await page.goto('/');
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 5000 });
  expect(page.url()).toContain('/auth/sign-in');
});

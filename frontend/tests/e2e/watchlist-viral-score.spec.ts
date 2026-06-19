/**
 * TASK-121 e2e — Signal Desk row shows viral_score (live_score 0-100) as the
 * PRIMARY badge, with velocity demoted to the badge tooltip (title).
 *
 * Drives the real SPA at the edge (baseURL from playwright.config.ts). Auth is
 * real (register + UI login). The `/watchlists` list response is intercepted and
 * given a row whose `signal` carries the exact contract the SPA codes against
 * (gen.types.ts: live_score / live_velocity / sparkline_24h) — mirroring the
 * DB-seeded scenario (viral_score=35, velocity=0.3). This pins the assertion to
 * the rendered badge regardless of the live backend's score freshness.
 *
 * Asserts (TASK-121 AC):
 *  - primary badge text === rounded viral_score ("35"), NOT "×0.0 baseline"
 *  - badge tier class is `warm` (35 ≥ SCORE_WARM_THRESHOLD=20, < SCORE_HOT=40)
 *  - badge title (tooltip) carries BOTH the score and the velocity ×baseline part
 *  - a real sparkline (spark__line) is rendered, not the empty placeholder
 *  - a SCREENSHOT is captured as evidence
 *
 * Runs against the real SPA at the nginx edge (baseURL from playwright.config.ts
 * → HTTP_PORT, default :80) — the same `make up` stack as the other watchlist
 * e2e specs. The frontend image is built from current source (TASK-096/121 are
 * merged), so no separate dev server is needed. Auth + pack-subscribe are
 * proxied to the real backend; the `signal` payload is injected client-side (the
 * live backend may serve signal-less rows).
 */

import { test, expect, type Page } from '@playwright/test';

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-t121.example.com`;

// Seeded viral_score scenario (matches the psql-seeded scores row for user 99).
const SEEDED_VIRAL_SCORE = 35; // viral_score (live_score 0-100)
const SEEDED_VELOCITY = 0.3; // live_velocity (×baseline)

async function registerAndLogin(page: Page, email: string, password: string) {
  await page.request.post('/api/v1/auth/register', {
    data: { email, password },
    headers: { 'Content-Type': 'application/json' },
  });
  await page.goto('/auth/sign-in');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel(/^Password/i).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/auth/sign-in'), {
    timeout: 10_000,
  });
}

// One watchlist row carrying a live viral_score signal (the contract the SPA
// renders). Hourly sparkline (oldest→newest) so the row draws a real spark line.
function watchlistWithSignal() {
  return [
    {
      id: 461,
      user_id: 99,
      topic: 'verify-t121',
      channel: { handle: '@t121verifychan', kind: 'telegram' },
      alert_config: { score_threshold: 20, min_channels: 1, notification_lang: 'ru' },
      signal: {
        live_velocity: SEEDED_VELOCITY,
        live_score: SEEDED_VIRAL_SCORE,
        sparkline_24h: [18.2, 24.5, 30.8, SEEDED_VIRAL_SCORE],
        last_alert_at: null,
      },
    },
  ];
}

test('TASK-121 — Signal Desk row shows viral_score badge as primary, velocity in tooltip', async ({
  page,
}) => {
  await page.context().clearCookies();

  const email = uniqueEmail('t121');
  const password = 'S3curePassw0rd!';

  await registerAndLogin(page, email, password);

  // Real watchlist rows so the auth-guard's onboarding check passes naturally
  // (Free: PACKS=1 → pack-subscribe creates rows). The live (stale) backend
  // returns these rows WITHOUT a `signal` (it predates TASK-096), so we then
  // intercept the client list query and attach the viral_score signal — the
  // exact contract the SPA renders.
  const sub = await page.request.post('/api/v1/packs/crypto-ru/subscribe', {
    headers: { 'Content-Type': 'application/json' },
  });
  expect(sub.status()).toBe(200);

  // Intercept the client list GET and inject the live viral_score signal onto
  // the first row (broad glob: matches with/without trailing slash or query).
  let listIntercepts = 0;
  await page.route('**/api/v1/watchlists**', async (route) => {
    const req = route.request();
    if (req.method() !== 'GET' || /\/watchlists\/[^/?]+/.test(new URL(req.url()).pathname)) {
      return route.fallback();
    }
    listIntercepts += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(watchlistWithSignal()),
    });
  });

  // The SSR layer hydrates the React-Query cache from window.__INITIAL_STATE__,
  // so the client would NOT refetch the (signal-less, stale-backend) list within
  // staleTime. Strip the watchlists query from the injected state before hydration
  // → the client refetches → our intercept supplies the viral_score signal.
  // (Per initial-state.types.ts: a missing/mismatched query key forces a refetch.)
  await page.addInitScript(() => {
    const strip = (s: { queries?: { key: unknown[] }[] } | undefined) => {
      if (!s?.queries) return s;
      return {
        ...s,
        queries: s.queries.filter(
          (q) => !(Array.isArray(q.key) && q.key[0] === 'watchlists'),
        ),
      };
    };
    let value: unknown;
    Object.defineProperty(window, '__INITIAL_STATE__', {
      configurable: true,
      set(v) {
        value = strip(v as { queries?: { key: unknown[] }[] });
      },
      get() {
        return value;
      },
    });
  });

  await page.goto('/watchlists', { waitUntil: 'networkidle' });
  await expect(page).toHaveURL(/\/watchlists/, { timeout: 15_000 });
  expect(listIntercepts).toBeGreaterThan(0);

  // The primary live-signal badge: viral_score as a rounded integer.
  const badge = page.locator('td .spark .vel-badge').first();
  await expect(badge).toBeVisible({ timeout: 10_000 });

  // AC: primary badge text === rounded viral_score, NOT the velocity ×baseline.
  await expect(badge).toHaveText(String(SEEDED_VIRAL_SCORE));
  await expect(badge).not.toHaveText(/baseline/);
  await expect(badge).not.toHaveText(/×/);

  // AC: tier colour class — 35 is warm (≥20, <40), reusing the .vel-badge CSS.
  await expect(badge).toHaveClass(/vel-badge/);
  await expect(badge).toHaveClass(/warm/);

  // AC: velocity is demoted to the badge tooltip (title), kept (not removed).
  const title = await badge.getAttribute('title');
  expect(title).toContain(`Live signal ${SEEDED_VIRAL_SCORE}/100`);
  expect(title).toContain(`velocity ×${SEEDED_VELOCITY.toFixed(1)} baseline`);

  // AC: a real sparkline is rendered (not the dashed empty placeholder).
  await expect(page.locator('td .spark svg.spark__line').first()).toBeVisible();

  // Evidence screenshot.
  await page.screenshot({
    path: 'playwright-report/task-121-viral-score-badge.png',
    fullPage: true,
  });
});

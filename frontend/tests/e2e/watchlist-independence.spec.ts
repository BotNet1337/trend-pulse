/**
 * TASK-126 e2e — Signal Desk row shows the source-independence chip
 * ("N independent sources") with an HONEST tooltip, and HIDES it when
 * `effective_sources` is null / below MIN_INDEPENDENCE_DISPLAY.
 *
 * Mirrors the TASK-121 viral-score e2e harness: drives the real SPA at the
 * nginx edge (baseURL from playwright.config.ts → HTTP_PORT, default :80), the
 * same `make up` stack as the other watchlist e2e specs — the frontend image is
 * built from current source (TASK-126 is merged), so no separate dev server is
 * needed. Auth is real (register + UI login, proxied to the live backend); the
 * `/watchlists` list response is intercepted and given rows carrying the exact
 * contract the SPA codes against (gen.types.ts: WatchlistSignal.effective_sources).
 *
 * Asserts (TASK-126 AC4 / AC6):
 *  - row with effective_sources=3 → chip text "3 independent sources" visible
 *  - chip tooltip is HONEST: "organic spread signal, not a coordination verdict"
 *  - row with effective_sources=null → NO independence chip (hidden, neutral)
 *  - row with effective_sources=1 (single-source, < MIN_INDEPENDENCE_DISPLAY) → hidden
 *  - a SCREENSHOT is captured as evidence
 */

import { test, expect, type Page } from '@playwright/test';

// baseURL comes from playwright.config.ts (the nginx edge, default :80). The
// config also sets the CSRF Origin header to that same origin so real
// auth/subscribe mutations are accepted by the backend allow-list.

const uniqueEmail = (prefix: string) =>
  `${prefix}-${Date.now()}@playwright-t126.example.com`;

// Multi-channel cluster → effective_sources = 3 (chip shows "3 independent sources").
const MULTI_EFFECTIVE_SOURCES = 3;

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

// Three rows: multi-source (chip shown), single-source ~1 (hidden), null (hidden).
function watchlistsWithIndependence() {
  const baseSignal = {
    live_velocity: 0.3,
    live_score: 35,
    sparkline_24h: [18.2, 24.5, 30.8, 35],
    last_alert_at: null,
  };
  return [
    {
      id: 561,
      user_id: 99,
      topic: 'multi-source',
      channel: { handle: '@t126multi', kind: 'telegram' },
      alert_config: { score_threshold: 20, min_channels: 1, notification_lang: 'ru' },
      signal: { ...baseSignal, effective_sources: MULTI_EFFECTIVE_SOURCES },
    },
    {
      id: 562,
      user_id: 99,
      topic: 'single-source',
      channel: { handle: '@t126single', kind: 'telegram' },
      alert_config: { score_threshold: 20, min_channels: 1, notification_lang: 'ru' },
      signal: { ...baseSignal, effective_sources: 1.0 },
    },
    {
      id: 563,
      user_id: 99,
      topic: 'no-independence',
      channel: { handle: '@t126null', kind: 'telegram' },
      alert_config: { score_threshold: 20, min_channels: 1, notification_lang: 'ru' },
      signal: { ...baseSignal, effective_sources: null },
    },
  ];
}

test('TASK-126 — independence chip renders honestly and hides below threshold', async ({
  page,
}) => {
  await page.context().clearCookies();

  const email = uniqueEmail('t126');
  const password = 'S3curePassw0rd!';
  await registerAndLogin(page, email, password);

  // Real subscribe so the onboarding guard passes; the live (stale) backend serves
  // signal-less rows, so we then intercept the client list query and inject the
  // effective_sources contract the SPA renders.
  const sub = await page.request.post('/api/v1/packs/crypto-ru/subscribe', {
    headers: { 'Content-Type': 'application/json' },
  });
  expect(sub.status()).toBe(200);

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
      body: JSON.stringify(watchlistsWithIndependence()),
    });
  });

  // Strip the watchlists query from the SSR-injected initial state so the client
  // refetches and our intercept supplies the effective_sources signal.
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

  // AC4: multi-source row shows the independence chip "3 independent sources".
  const chip = page.locator('.vel-badge--independence');
  await expect(chip).toHaveCount(1, { timeout: 10_000 });
  await expect(chip.first()).toBeVisible();
  await expect(chip.first()).toHaveText(`${MULTI_EFFECTIVE_SOURCES} independent sources`);

  // AC6: honest tooltip — organic-spread signal, NOT a coordination/anti-fraud verdict.
  const tooltip = await chip.first().getAttribute('title');
  expect(tooltip).not.toBeNull();
  expect(tooltip!.toLowerCase()).toContain('organic spread signal');
  expect(tooltip!.toLowerCase()).toContain('not a coordination verdict');
  expect(tooltip).not.toMatch(/bot|fraud|coordinat\w+ detect/i);

  // AC4 (hidden): exactly ONE chip across THREE rows — single-source(~1) and null hide it.
  await expect(page.locator('.vel-badge--independence')).toHaveCount(1);

  await page.screenshot({
    path: 'playwright-report/task-126-independence-chip.png',
    fullPage: true,
  });
});

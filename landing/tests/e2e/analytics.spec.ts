import { test, expect, type Page } from '@playwright/test';

/**
 * TASK-068 e2e — Plausible analytics (AC1-AC4).
 *
 * plausible.io is never reached for real: the script is either aborted
 * (blocked-adblock scenario) or replaced with a stub that forwards events to
 * plausible.io/api/event, which is intercepted and recorded.
 */

const DATA_DOMAIN = 'foresignal.biz';
const SIGNUP_URL_GLOB = 'https://app.foresignal.biz/**';

/** Stub for plausible.io/js/script.js: forwards plausible() calls to the event API. */
const PLAUSIBLE_STUB = `
  window.plausible = function (name) {
    void fetch('https://plausible.io/api/event', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ n: name, d: '${DATA_DOMAIN}' }),
      keepalive: true,
    });
  };
`;

/** Serve a local stand-in for the external SPA so CTA navigation stays offline. */
async function stubSignupTarget(page: Page): Promise<void> {
  await page.route(SIGNUP_URL_GLOB, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>spa stub</body></html>' }),
  );
}

/** Intercept the Plausible event API and record event names. */
async function captureEvents(page: Page): Promise<string[]> {
  const events: string[] = [];
  await page.route('https://plausible.io/js/script.js', (route) =>
    route.fulfill({ status: 200, contentType: 'application/javascript', body: PLAUSIBLE_STUB }),
  );
  await page.route('https://plausible.io/api/event', (route) => {
    const body = route.request().postData();
    if (body) events.push((JSON.parse(body) as { n: string }).n);
    return route.fulfill({ status: 202, contentType: 'text/plain', body: 'ok' });
  });
  return events;
}

test.describe('TASK-068 Plausible analytics', () => {
  test('AC1 — head has exactly one Plausible tag with the configured data-domain', async ({ page }) => {
    for (const path of ['/', '/pricing']) {
      await page.goto(path);
      const tags = page.locator('head script[data-domain]');
      await expect(tags).toHaveCount(1);
      await expect(tags).toHaveAttribute('data-domain', DATA_DOMAIN);
      await expect(tags).toHaveAttribute('src', 'https://plausible.io/js/script.js');
    }
  });

  test('AC2 — blocked plausible.io: CTA click still navigates, no console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    const isExpectedNoise = (text: string): boolean =>
      // The browser itself logs the blocked analytics request — expected in the adblock scenario.
      text.includes('Failed to load resource') ||
      // Pre-existing hydration mismatch (React #418), reproduced on baseline main
      // without this task's changes — tracked outside TASK-068.
      /Minified React error #418|Hydration failed/.test(text);
    page.on('console', (msg) => {
      if (msg.type() === 'error' && !isExpectedNoise(msg.text())) consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => {
      if (!isExpectedNoise(String(err))) consoleErrors.push(String(err));
    });

    await page.route('https://plausible.io/**', (route) => route.abort());
    await stubSignupTarget(page);

    await page.goto('/');
    await page.locator('section a[href*="/sign-up"]').first().click();
    await page.waitForURL('**/sign-up');

    expect(consoleErrors).toEqual([]);
  });

  test('AC2 — hero CTA click sends sign_up_click to the Plausible event API', async ({ page }) => {
    const events = await captureEvents(page);
    await stubSignupTarget(page);

    await page.goto('/');
    await page.locator('section a[href*="/sign-up"]').first().click();
    await page.waitForURL('**/sign-up');

    await expect.poll(() => events).toContain('sign_up_click');
  });

  test('AC2 — visiting /pricing sends pricing_view exactly once', async ({ page }) => {
    const events = await captureEvents(page);

    await page.goto('/pricing');
    await expect.poll(() => events.filter((e) => e === 'pricing_view').length).toBe(1);
    // Give a potential duplicate (StrictMode/remount) a moment to fire, then re-assert.
    await page.waitForTimeout(500);
    expect(events.filter((e) => e === 'pricing_view')).toHaveLength(1);
  });

  test('AC3 — Reject All sets plausible_ignore; re-enabling analytics clears it', async ({ page }) => {
    await page.goto('/');

    // First visit: banner is shown.
    await page.getByRole('button', { name: 'Reject All' }).first().click();
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('plausible_ignore')))
      .toBe('true');

    // Re-open preferences from the footer, enable Analytics, save → opt-out cleared.
    await page.getByRole('button', { name: 'Cookie Preferences' }).click();
    // Switches exist only inside the modal: 0 = essential (disabled), 1 = analytics.
    await page.getByRole('switch').nth(1).click();
    await page.getByRole('button', { name: 'Save Preferences' }).click();
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('plausible_ignore')))
      .toBe(null);
  });

  test('AC4 — legal pages no longer mention Google Analytics', async ({ page }) => {
    for (const path of ['/cookie-policy', '/dpa', '/do-not-sell-or-share']) {
      await page.goto(path);
      const html = await page.content();
      expect(html, `${path} must not mention Google Analytics`).not.toMatch(/Google Analytics|GA4|_ga/);
    }
    // DPA subprocessor table lists Plausible instead.
    await page.goto('/dpa');
    expect(await page.content()).toMatch(/Plausible Insights/);
  });
});

import { test, expect } from '@playwright/test';

/**
 * TASK-067 e2e — Proof of Speed section + showcase links (AC1, AC2, AC4).
 *
 * Two modes, driven by how the server under test was started:
 * - default (CASES_API_URL unset/empty): the section must be ABSENT and the
 *   page must still render fine (graceful fallback, AC2);
 * - mock mode (run the SSR server with CASES_API_URL pointing at a stub that
 *   returns >=3 cases, then set E2E_CASES_MOCK=1 for Playwright): the section
 *   must be present with times/lead-time/score (AC1).
 *
 * The fetch happens server-side (SSR), so `page.route` cannot intercept it —
 * the mock has to live behind CASES_API_URL of the server process itself.
 */
const casesMockEnabled = process.env['E2E_CASES_MOCK'] === '1';

test.describe('Proof of Speed — graceful fallback (no CASES_API_URL)', () => {
  test.skip(casesMockEnabled, 'server runs with a cases mock — fallback not testable');

  test('AC2 — section absent, home still renders all key sections', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);

    await expect(page.locator('#proof-of-speed')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: /proof of speed/i })).toHaveCount(0);

    // Smoke anchors stay intact (subset of smoke.spec.ts AC2)
    await expect(page.getByRole('heading', { name: /how it works/i })).toBeVisible();
    await expect(page.locator('footer')).toBeVisible();
  });
});

test.describe('Proof of Speed — live cases (server started with mock CASES_API_URL)', () => {
  test.skip(!casesMockEnabled, 'requires SSR server started with stubbed CASES_API_URL');

  test('AC1 — section shows >=3 cases with detected/mainstream/lead-time/score', async ({ page }) => {
    await page.goto('/');

    const section = page.locator('#proof-of-speed');
    await expect(section).toBeVisible();
    await expect(section.getByRole('heading', { name: /proof of speed/i })).toBeVisible();

    const sectionText = await section.innerText();
    expect(sectionText).toMatch(/detected\s+\d{2}:\d{2}/i);
    expect(sectionText).toMatch(/mainstream\s+\d{2}:\d{2}/i);
    expect(sectionText).toMatch(/(min|h)(\s+\d+\s+min)?\s+ahead|<1 min ahead/i);
    expect(sectionText).toMatch(/Score:\s*\d+/);

    const cards = section.locator('.grid > div');
    expect(await cards.count()).toBeGreaterThanOrEqual(3);

    // channels_count must never be rendered inside case cards (MVP=1 weakens the proof)
    const firstCardText = await cards.first().innerText();
    expect(firstCardText).not.toMatch(/channel/i);
  });

  test('AC1 — cases are present in raw SSR HTML (SEO)', async ({ request }) => {
    const response = await request.get('/');
    expect(response.status()).toBe(200);
    const html = await response.text();
    expect(html).toContain('id="proof-of-speed"');
    expect(html).toContain('__INITIAL_STATE__');
  });
});

test.describe('Showcase Telegram link (config-driven)', () => {
  test('AC4 — links follow showcaseTelegramUrl from config.json', async ({ page }) => {
    await page.goto('/');

    const config = await page.evaluate(async () => {
      const res = await fetch('/config.json');
      return (await res.json()) as { showcaseTelegramUrl?: string };
    });
    const showcaseUrl = config.showcaseTelegramUrl ?? '';

    const heroLink = page.getByRole('link', { name: /see live detections in telegram/i });
    const footerLink = page.locator('footer').getByRole('link', { name: /telegram showcase/i });

    if (showcaseUrl === '') {
      await expect(heroLink).toHaveCount(0);
      await expect(footerLink).toHaveCount(0);
    } else {
      await expect(heroLink).toHaveAttribute('href', showcaseUrl);
      await expect(footerLink).toHaveAttribute('href', showcaseUrl);
    }
  });
});

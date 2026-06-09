import { test, expect } from '@playwright/test';

/**
 * TASK-018 smoke e2e — RED anchor (AC1-AC4)
 * Verifies TrendPulse brand, key sections, CTA href, compliance footer.
 */

test.describe('TrendPulse landing smoke', () => {
  test('AC1 — page loads with TrendPulse brand (not template brand)', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/TrendPulse/i);
    // Must NOT show old template brand
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toMatch(/PostBolt/i);
    // Brand visible in nav
    await expect(page.locator('nav').getByText('TrendPulse')).toBeVisible();
  });

  test('AC2 — key sections present: hero with viral-alert, how-it-works, features, pricing, footer', async ({ page }) => {
    await page.goto('/');

    // Hero: value prop and viral-alert example
    const heroSection = page.locator('section').first();
    await expect(heroSection).toBeVisible();

    // Viral alert example text anywhere on page
    const pageText = await page.locator('body').innerText();
    expect(pageText).toMatch(/viral alert/i);
    expect(pageText).toMatch(/Score/i);

    // How it works section
    const howItWorks = page.getByRole('heading', { name: /how it works/i });
    await expect(howItWorks).toBeVisible();

    // Features section
    const features = page.getByRole('heading', { name: /features|everything you need/i }).first();
    await expect(features).toBeVisible();

    // Pricing section — Free/Pro/Team
    const pricing = page.getByRole('heading', { name: /pricing/i }).first();
    await expect(pricing).toBeVisible();
    expect(pageText).toMatch(/Free/i);
    expect(pageText).toMatch(/Pro/i);
    expect(pageText).toMatch(/Team/i);

    // Footer
    const footer = page.locator('footer');
    await expect(footer).toBeVisible();
  });

  test('AC3 — CTA button links to /sign-up', async ({ page }) => {
    await page.goto('/');
    // Primary CTA button href
    const ctaLink = page.locator('a[href*="/sign-up"]').first();
    await expect(ctaLink).toBeVisible();
    const href = await ctaLink.getAttribute('href');
    expect(href).toMatch(/\/sign-up/);
  });

  test('AC4 — compliance footer: privacy, ToS, retention 48h, public-only', async ({ page }) => {
    await page.goto('/');
    const footer = page.locator('footer');

    // Privacy policy link
    await expect(footer.getByRole('link', { name: /privacy/i })).toBeVisible();

    // Terms of service link
    await expect(footer.getByRole('link', { name: /terms/i })).toBeVisible();

    // Retention and public-only mentioned somewhere on page (section or footer)
    const pageText = await page.locator('body').innerText();
    expect(pageText).toMatch(/48.?h(ours?)?|48-hour/i);
    expect(pageText).toMatch(/public.{0,30}channel/i);
  });

  test('AC4 — privacy-policy page mentions 48h retention and public channels', async ({ page }) => {
    await page.goto('/privacy-policy');
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/TrendPulse/i);
    expect(bodyText).not.toMatch(/PostBolt/i);
    expect(bodyText).toMatch(/48.?h(ours?)?|48-hour/i);
    expect(bodyText).toMatch(/public.{0,30}channel/i);
  });

  test('AC4 — terms-of-service page has TrendPulse brand', async ({ page }) => {
    await page.goto('/terms-of-service');
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/TrendPulse/i);
    expect(bodyText).not.toMatch(/PostBolt/i);
  });
});

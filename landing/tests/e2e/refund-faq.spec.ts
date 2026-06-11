import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

const SITE = JSON.parse(
  readFileSync(new URL('../../public/config.json', import.meta.url), 'utf8'),
) as { contactEmail: string; legal: { effectiveDate: string } };

/**
 * TASK-071 refund-policy + FAQ e2e — RED anchor (AC1-AC3)
 * Verifies the /refund-policy legal page, the footer/pricing/ToS links to it,
 * and the expanded crypto-onboarding FAQ on the home page.
 */

test.describe('Refund Policy page (AC1)', () => {
  test('renders with 200, key guarantees, and config-driven contact email', async ({ page }) => {
    const response = await page.goto('/refund-policy');
    expect(response?.status()).toBe(200);

    await expect(page.getByRole('heading', { name: 'Refund Policy' })).toBeVisible();
    await expect(page.getByText(`Last updated: ${SITE.legal.effectiveDate}`)).toBeVisible();

    // textContent: accordion answers stay in the DOM even when collapsed.
    const bodyText = (await page.locator('body').textContent()) ?? '';
    expect(bodyText).toMatch(/7-day money-back/i);
    expect(bodyText).toMatch(/first payment/i);
    expect(bodyText).toMatch(/USDT/);
    expect(bodyText).toMatch(/case-by-case/i);
    expect(bodyText).toMatch(/14[- ]day/i); // EU withdrawal right
    expect(bodyText).toContain(SITE.contactEmail);
  });
});

test.describe('Refund Policy links (AC2)', () => {
  test('footer Legal list links to /refund-policy from home', async ({ page }) => {
    await page.goto('/');
    const footerLink = page.locator('footer').getByRole('link', { name: /refund policy/i });
    await expect(footerLink).toBeVisible();
    await footerLink.click();
    await expect(page).toHaveURL(/\/refund-policy$/);
    await expect(page.getByRole('heading', { name: 'Refund Policy' })).toBeVisible();
  });

  test('pricing page links to /refund-policy near the payment note', async ({ page }) => {
    await page.goto('/pricing');
    const refundLink = page.locator('a[href="/refund-policy"]').first();
    await expect(refundLink).toBeVisible();
    const bodyText = (await page.locator('body').textContent()) ?? '';
    expect(bodyText).toMatch(/7-day money-back/i);
  });

  test('ToS Billing refund bullet links to /refund-policy and is no longer unconditionally non-refundable', async ({ page }) => {
    await page.goto('/terms-of-service');
    const refundLink = page.locator('a[href="/refund-policy"]').first();
    await expect(refundLink).toBeAttached();
    const bodyText = (await page.locator('body').textContent()) ?? '';
    expect(bodyText).toMatch(/7-day money-back/i);
    expect(bodyText).not.toMatch(/fees are non-refundable/i);
  });
});

test.describe('Home FAQ crypto onboarding (AC3)', () => {
  test('the five pre-sale questions open and answer', async ({ page }) => {
    await page.goto('/');
    const faq = page.locator('#faq');
    await expect(faq).toBeVisible();

    const cases: Array<{ question: RegExp; answer: RegExp }> = [
      { question: /never paid with crypto/i, answer: /NOWPayments checkout/i },
      { question: /30-minute delay on the Free plan/i, answer: /real time/i },
      { question: /What are curated channel packs/i, answer: /bundles of public Telegram channels/i },
      { question: /How do I get an API key/i, answer: /Trader plan/i },
      { question: /How do I cancel my subscription/i, answer: /prepaid/i },
    ];

    for (const { question, answer } of cases) {
      const button = faq.getByRole('button', { name: question });
      await expect(button).toBeVisible();
      await button.click();
      await expect(button).toHaveAttribute('aria-expanded', 'true');
      await expect(faq.getByText(answer).first()).toBeVisible();
    }
  });

  test('refund question links to /refund-policy instead of pointing at ToS', async ({ page }) => {
    await page.goto('/');
    const faq = page.locator('#faq');
    await faq.getByRole('button', { name: /Do you offer refunds/i }).click();
    const refundLink = faq.locator('a[href="/refund-policy"]').first();
    await expect(refundLink).toBeVisible();
  });

  test('FAQ names the top plan Trader, never Team', async ({ page }) => {
    await page.goto('/');
    const faqText = (await page.locator('#faq').textContent()) ?? '';
    expect(faqText).toMatch(/Trader/);
    expect(faqText).not.toMatch(/\bTeam\b/);
  });
});

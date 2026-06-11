export const SITE_ROUTES = [
  '/',
  '/pricing',
  '/about',
  '/contact',
  '/privacy-policy',
  '/terms-of-service',
  '/refund-policy',
  '/cookie-policy',
  '/acceptable-use-policy',
  '/accessibility-statement',
  '/security',
  '/dpa',
  '/do-not-sell-or-share',
  '/blog',
  '/blog/detect-viral-telegram-content-early',
  '/blog/telegram-trend-alerts-vs-tgstat-telemetr',
  '/blog/crypto-payments-for-saas-guide',
] as const;

export type SiteRoute = (typeof SITE_ROUTES)[number];



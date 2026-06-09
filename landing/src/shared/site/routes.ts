export const SITE_ROUTES = [
  '/',
  '/pricing',
  '/about',
  '/contact',
  '/privacy-policy',
  '/terms-of-service',
  '/cookie-policy',
  '/acceptable-use-policy',
  '/accessibility-statement',
  '/security',
  '/dpa',
  '/do-not-sell-or-share',
] as const;

export type SiteRoute = (typeof SITE_ROUTES)[number];



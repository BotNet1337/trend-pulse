import { SITE } from '@/shared/site/constants';
import type { SiteRoute } from '@/shared/site/routes';

/**
 * TASK-073: blog article registry — single source for the /blog index page,
 * router paths, SITE_ROUTES coverage and per-route SEO meta (seo.ts).
 * Content honesty contract (lesson task-018): every fact in articles derives
 * from docs/product/overview.md §6 and the live config.json — never invented.
 */
export type BlogArticleMeta = {
  slug: string;
  /** Registered route path — membership in SITE_ROUTES is unit-tested. */
  path: SiteRoute;
  /** h1 + JSON-LD headline; brand always via SITE.brandName. */
  title: string;
  seoTitle: string;
  seoDescription: string;
  /** ISO date (YYYY-MM-DD). */
  datePublished: string;
  readingTimeMinutes: number;
  /** Index-page teaser. */
  excerpt: string;
};

export const BLOG_PATH = '/blog';

function article(meta: Omit<BlogArticleMeta, 'path'>): BlogArticleMeta {
  // Safe: every article path is asserted to be in SITE_ROUTES by tests/unit/blog.test.ts.
  return { ...meta, path: `${BLOG_PATH}/${meta.slug}` as SiteRoute };
}

export const BLOG_ARTICLES: readonly BlogArticleMeta[] = [
  article({
    slug: 'detect-viral-telegram-content-early',
    title: 'How to Detect Viral Telegram Content Early',
    seoTitle: `How to Detect Viral Telegram Content Early — ${SITE.brandName} Blog`,
    seoDescription:
      'A practical guide to spotting Telegram posts going viral before mainstream media: manual signals, their limits, and how automated cross-channel detection works.',
    datePublished: '2026-06-11',
    readingTimeMinutes: 6,
    excerpt:
      'Cross-channel repetition, forward velocity, view spikes — the manual signals that a story is about to explode, and how automated detection scales them.',
  }),
  article({
    slug: 'telegram-trend-alerts-vs-tgstat-telemetr',
    title: `${SITE.brandName} vs TGStat vs Telemetr: Alerts vs Analytics`,
    seoTitle: `${SITE.brandName} vs TGStat vs Telemetr — Alerts vs Channel Analytics`,
    seoDescription: `An honest comparison: TGStat and Telemetr are channel catalogs and audience analytics platforms, ${SITE.brandName} is an alert-first viral content detector.`,
    datePublished: '2026-06-11',
    readingTimeMinutes: 5,
    excerpt:
      'They answer "how big is this channel?", we answer "what is exploding right now?" — an honest look at what each tool is actually for.',
  }),
  article({
    slug: 'crypto-payments-for-saas-guide',
    title: 'How to Pay for a SaaS Subscription with Crypto',
    seoTitle: `How to Pay for a SaaS Subscription with Crypto — ${SITE.brandName} Blog`,
    seoDescription:
      'Step-by-step guide to paying for a subscription with cryptocurrency via NOWPayments: invoices, coins and networks, confirmations, refunds in USDT, common pitfalls.',
    datePublished: '2026-06-11',
    readingTimeMinutes: 5,
    excerpt:
      'Wallet to active subscription in five steps: invoices, picking the right network, confirmation times, and how refunds work when there are no chargebacks.',
  }),
];

export function findArticleByPath(pathname: string): BlogArticleMeta | undefined {
  return BLOG_ARTICLES.find((a) => a.path === pathname);
}

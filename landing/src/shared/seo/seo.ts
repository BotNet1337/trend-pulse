import { SITE } from '@/shared/site/constants';
import { PLAUSIBLE_SCRIPT_URL } from '@/shared/analytics/track';

function escapeHtml(s: string): string {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function canonicalFor(pathname: string): string {
  return new URL(pathname, SITE.siteUrl).toString();
}

function routeMeta(pathname: string): { title: string; description: string } {
  const baseTitle = `${SITE.brandName}`;
  const baseDesc =
    `${SITE.brandName} detects viral content from public Telegram channels in real time. Get alerts before trending topics explode — free plan available.`;

  switch (pathname) {
    case '/':
      return { title: `${baseTitle} — ${SITE.valueProp}`, description: baseDesc };
    case '/pricing':
      return {
        title: `${baseTitle} — Pricing`,
        description:
          'Free (curated packs), Pro ($29/mo), and Trader ($99/mo) plans. Crypto payments only. Start tracking viral Telegram trends for free.',
      };
    case '/about':
      return {
        title: `About ${baseTitle} — Viral Telegram Content Detector`,
        description: `${SITE.brandName} is building a real-time viral content detector for public Telegram channels. Public channels only, 48-hour retention.`,
      };
    case '/contact':
      return {
        title: `Contact ${baseTitle}`,
        description: `Questions about ${SITE.brandName}? Contact us or email ${SITE.contactEmail}.`,
      };
    case '/faq':
      return {
        title: `${baseTitle} — FAQ`,
        description: 'Common questions about viral detection, Telegram channels, privacy, retention, and pricing.',
      };
    case '/privacy-policy':
      return {
        title: `${baseTitle} — Privacy Policy`,
        description: `Privacy Policy for ${SITE.brandName}. Public channels only, 48-hour raw content retention.`,
      };
    case '/terms-of-service':
      return { title: `${baseTitle} — Terms of Service`, description: `Terms of Service for ${SITE.brandName}.` };
    case '/refund-policy':
      return {
        title: `${baseTitle} — Refund Policy`,
        description: `Refund Policy for ${SITE.brandName}: 7-day money-back guarantee on your first payment, refunded manually in USDT.`,
      };
    case '/cookie-policy':
      return { title: `${baseTitle} — Cookie Policy`, description: `Cookie Policy for ${SITE.brandName}.` };
    case '/acceptable-use-policy':
      return { title: `${baseTitle} — Acceptable Use Policy`, description: `Acceptable Use Policy for ${SITE.brandName}.` };
    case '/accessibility-statement':
      return { title: `${baseTitle} — Accessibility`, description: `Accessibility Statement for ${SITE.brandName}.` };
    case '/security':
      return {
        title: `${baseTitle} — Security`,
        description: `Security practices and responsible disclosure for ${SITE.brandName}.`,
      };
    case '/dpa':
      return { title: `${baseTitle} — DPA Overview`, description: `Data Processing Addendum overview for ${SITE.brandName}.` };
    case '/do-not-sell-or-share':
      return { title: `${baseTitle} — Do Not Sell/Share`, description: `CCPA/CPRA opt-out information for ${SITE.brandName}.` };
    default:
      return { title: `${baseTitle} — Not Found`, description: baseDesc };
  }
}

function buildJsonLd(pathname: string): string[] {
  const org = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE.brandName,
    url: SITE.siteUrl,
    contactPoint: {
      '@type': 'ContactPoint',
      email: SITE.contactEmail,
      contactType: 'customer support',
    },
  };

  const website = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SITE.brandName,
    url: SITE.siteUrl,
  };

  const jsonlds: unknown[] = [org, website];

  if (pathname === '/') {
    jsonlds.push({
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: SITE.brandName,
      applicationCategory: 'ProductivityApplication',
      operatingSystem: 'Web',
      offers: {
        '@type': 'Offer',
        price: '0',
        priceCurrency: 'USD',
        availability: 'https://schema.org/PreOrder',
      },
      description:
        'Real-time viral content detector for public Telegram channels. Get alerts when topics trend — free plan available.',
      url: SITE.siteUrl,
    });
  }

  return jsonlds.map((obj) => `<script type="application/ld+json">${escapeHtml(JSON.stringify(obj))}</script>`);
}

/**
 * TASK-068: Plausible tag for every SSR page. Empty domain (config.json
 * `plausibleDomain`) disables analytics entirely — no tag is rendered.
 */
export function buildPlausibleTag(domain: string): string | null {
  if (!domain) return null;
  return `<script defer data-domain="${escapeHtml(domain)}" src="${PLAUSIBLE_SCRIPT_URL}"></script>`;
}

export function buildHeadTags(path: string): string {
  const pathname = (() => {
    try {
      return new URL(path, SITE.siteUrl).pathname;
    } catch {
      return path.split('?')[0] || '/';
    }
  })();

  const { title, description } = routeMeta(pathname);
  const canonical = canonicalFor(pathname);
  const ogImage = new URL('/og.svg', SITE.siteUrl).toString();
  const plausibleTag = buildPlausibleTag((SITE as { plausibleDomain?: string }).plausibleDomain ?? '');

  const tags = [
    `<title>${escapeHtml(title)}</title>`,
    `<meta name="description" content="${escapeHtml(description)}" />`,
    `<link rel="canonical" href="${escapeHtml(canonical)}" />`,
    `<meta name="robots" content="index, follow" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="${escapeHtml(SITE.brandName)}" />`,
    `<meta property="og:title" content="${escapeHtml(title)}" />`,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
    `<meta property="og:url" content="${escapeHtml(canonical)}" />`,
    `<meta property="og:image" content="${escapeHtml(ogImage)}" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${escapeHtml(title)}" />`,
    `<meta name="twitter:description" content="${escapeHtml(description)}" />`,
    `<meta name="twitter:image" content="${escapeHtml(ogImage)}" />`,
    ...buildJsonLd(pathname),
    ...(plausibleTag ? [plausibleTag] : []),
  ];

  return tags.join('\n');
}



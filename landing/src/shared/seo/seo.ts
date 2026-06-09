import { SITE } from '@/shared/site/constants';

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
    'Plan, schedule, and publish posts across all your social platforms from one workspace—one workflow instead of juggling every network separately.';

  switch (pathname) {
    case '/':
      return { title: `${baseTitle} — ${SITE.valueProp}`, description: baseDesc };
    case '/pricing':
      return {
        title: `${baseTitle} — Pricing`,
        description:
          'Early access pricing is evolving. Join the waitlist to get launch updates and the first available plans.',
      };
    case '/affiliate':
      return {
        title: `${baseTitle} — Affiliate Program`,
        description:
          `Share ${SITE.brandName} and earn commission on qualifying purchases. Program details may evolve during early access.`,
      };
    case '/about':
      return {
        title: `About ${baseTitle} — Cross-platform social publishing`,
        description: `${SITE.brandName} is building a simpler way to plan, schedule, and publish across social platforms with a clear roadmap.`,
      };
    case '/contact':
      return {
        title: `Contact ${baseTitle}`,
        description: `Join early access, ask a question, or email ${SITE.contactEmail}.`,
      };
    case '/faq':
      return {
        title: `${baseTitle} — FAQ`,
        description: 'Common questions about publishing, supported platforms, scheduling, privacy, and early access.',
      };
    case '/privacy-policy':
      return { title: `${baseTitle} — Privacy Policy`, description: `Privacy Policy for ${SITE.brandName}.` };
    case '/terms-of-service':
      return { title: `${baseTitle} — Terms of Service`, description: `Terms of Service for ${SITE.brandName}.` };
    case '/cookie-policy':
      return { title: `${baseTitle} — Cookie Policy`, description: `Cookie Policy for ${SITE.brandName}.` };
    case '/acceptable-use-policy':
      return { title: `${baseTitle} — Acceptable Use Policy`, description: `Acceptable Use Policy for ${SITE.brandName}.` };
    case '/refund-policy':
      return { title: `${baseTitle} — Refund Policy`, description: `Refund Policy for ${SITE.brandName}.` };
    case '/accessibility-statement':
      return { title: `${baseTitle} — Accessibility`, description: `Accessibility Statement for ${SITE.brandName}.` };
    case '/security':
      return { title: `${baseTitle} — Security`, description: `Security practices and responsible disclosure.` };
    case '/dpa':
      return { title: `${baseTitle} — DPA Overview`, description: `Data Processing Addendum overview.` };
    case '/do-not-sell-or-share':
      return { title: `${baseTitle} — Do Not Sell/Share`, description: `CCPA/CPRA opt-out information.` };
    case '/coming-soon':
      return { title: `${baseTitle} — Coming Soon`, description: `This page is coming soon.` };
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
        'Plan, schedule, and publish social content across platforms from one workspace—early access roadmap in progress.',
      url: SITE.siteUrl,
    });
  }

  return jsonlds.map((obj) => `<script type="application/ld+json">${escapeHtml(JSON.stringify(obj))}</script>`);
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
  ];

  return tags.join('\n');
}



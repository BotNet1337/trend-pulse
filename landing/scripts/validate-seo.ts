import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { SITE_ROUTES } from '../src/shared/site/routes';
import { buildHeadTags } from '../src/shared/seo/seo';
import { SITE } from '../src/shared/site/constants';

const robotsTxtPath = fileURLToPath(new URL('../public/robots.txt', import.meta.url));

/**
 * TASK-067: robots.txt domain-drift guard. The template domain survived a
 * rebranding once (ai-port.me) — pin the Sitemap line to SITE.siteUrl forever.
 */
function validateRobotsTxt(): boolean {
  const expectedSitemapLine = `Sitemap: ${SITE.siteUrl}/sitemap.xml`;
  const robotsTxt = readFileSync(robotsTxtPath, 'utf8');
  if (!robotsTxt.includes(expectedSitemapLine)) {
    console.error(
      `[seo] robots.txt drift: expected "${expectedSitemapLine}" in ${robotsTxtPath}`,
    );
    return false;
  }
  const sitemapLines = robotsTxt
    .split('\n')
    .filter((line) => line.trim().toLowerCase().startsWith('sitemap:'));
  const foreign = sitemapLines.filter((line) => !line.includes(`${SITE.siteUrl}/sitemap.xml`));
  if (foreign.length > 0) {
    console.error(`[seo] robots.txt contains foreign sitemap line(s): ${foreign.join(' | ')}`);
    return false;
  }
  return true;
}

function extractMeta(nameOrProp: string, html: string): string | null {
  const re = new RegExp(
    `<meta\\s+(?:name|property)="${nameOrProp.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}"\\s+content="([^"]+)"\\s*/?>`,
    'i',
  );
  const m = html.match(re);
  return m?.[1] ?? null;
}

function extractTitle(html: string): string | null {
  const m = html.match(/<title>([^<]+)<\/title>/i);
  return m?.[1] ?? null;
}

function main() {
  const results = SITE_ROUTES.map((route) => {
    const head = buildHeadTags(route);
    const title = extractTitle(head);
    const desc = extractMeta('description', head);
    return { route, title, desc };
  });

  const missing = results.filter((r) => !r.title || !r.desc);
  const dupTitle = new Map<string, string[]>();
  for (const r of results) {
    if (!r.title) continue;
    const arr = dupTitle.get(r.title) ?? [];
    arr.push(r.route);
    dupTitle.set(r.title, arr);
  }
  const dupTitles = [...dupTitle.entries()].filter(([, routes]) => routes.length > 1);

  console.log(`[seo] routes=${results.length}`);
  if (!validateRobotsTxt()) {
    process.exitCode = 1;
  }
  if (missing.length > 0) {
    console.error(`[seo] missing title/description on: ${missing.map((m) => m.route).join(', ')}`);
    process.exitCode = 1;
  }
  if (dupTitles.length > 0) {
    console.warn('[seo] duplicate titles detected:');
    for (const [title, routes] of dupTitles) {
      console.warn(`  - ${title} :: ${routes.join(', ')}`);
    }
  }

  console.log(`[seo] ok site=${SITE_ROUTES.length}`);
}

main();



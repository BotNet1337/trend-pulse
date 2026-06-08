import fs from 'node:fs/promises';
import path from 'node:path';
import { SITE } from '../src/shared/site/constants';
import { SITE_ROUTES } from '../src/shared/site/routes';

function escapeXml(s: string): string {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

async function main() {
  const now = new Date().toISOString();

  const urls = SITE_ROUTES.map((route) => {
    const loc = new URL(route, SITE.siteUrl).toString();
    return [
      '  <url>',
      `    <loc>${escapeXml(loc)}</loc>`,
      `    <lastmod>${escapeXml(now)}</lastmod>`,
      '    <changefreq>weekly</changefreq>',
      '    <priority>0.5</priority>',
      '  </url>',
    ].join('\n');
  }).join('\n');

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    '</urlset>',
    '',
  ].join('\n');

  const outPath = path.resolve(process.cwd(), 'public', 'sitemap.xml');
  await fs.mkdir(path.dirname(outPath), { recursive: true });
  await fs.writeFile(outPath, xml, 'utf8');
  console.log(`[sitemap] wrote ${SITE_ROUTES.length} routes -> ${outPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});



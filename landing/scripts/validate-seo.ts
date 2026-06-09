import { SITE_ROUTES } from '../src/shared/site/routes';
import { buildHeadTags } from '../src/shared/seo/seo';

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



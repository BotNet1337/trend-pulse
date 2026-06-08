import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildHeadTags } from '../src/shared/seo/seo';
import { SITE_ROUTES } from '../src/shared/site/routes';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

type AuditResult = {
  missingSeo: { route: string; title: string | null; desc: string | null }[];
  footerLinksNotInRoutes: string[];
  routesNotLinkedInFooter: string[];
  pagesMissingH1: string[];
};

function extractTitle(html: string): string | null {
  const m = html.match(/<title>([^<]+)<\/title>/i);
  return m?.[1] ?? null;
}

function extractMeta(nameOrProp: string, html: string): string | null {
  const re = new RegExp(
    `<meta\\s+(?:name|property)="${nameOrProp.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}"\\s+content="([^"]+)"\\s*/?>`,
    'i',
  );
  const m = html.match(re);
  return m?.[1] ?? null;
}

function extractLinksFromTsx(source: string): string[] {
  const out = new Set<string>();
  const re = /\b(?:to|href)=["'](\/[^"']+)["']/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    const value = m[1];
    if (!value) continue;
    // Strip query/hash
    const normalized = value.split('#')[0]?.split('?')[0] ?? value;
    // Ignore mailto, external, etc. (regex already restricts to /)
    out.add(normalized);
  }
  return [...out];
}

async function listFilesRecursive(dir: string): Promise<string[]> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const e of entries) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      files.push(...(await listFilesRecursive(p)));
    } else {
      files.push(p);
    }
  }
  return files;
}

async function audit(): Promise<AuditResult> {
  const routes = [...SITE_ROUTES];

  const missingSeo = routes
    .map((route) => {
      const head = buildHeadTags(route);
      const title = extractTitle(head);
      const desc = extractMeta('description', head);
      return { route, title, desc };
    })
    .filter((r) => !r.title || !r.desc);

  const rootLayoutPath = path.resolve(__dirname, '../src/pages/layouts/root-layout.tsx');
  const rootLayout = await fs.readFile(rootLayoutPath, 'utf8');
  const footerLinks = extractLinksFromTsx(rootLayout);

  const routesAsStrings = routes as unknown as readonly string[];
  const footerLinksNotInRoutes = footerLinks.filter((l) => !routesAsStrings.includes(l));
  const routesNotLinkedInFooter = routes.filter((r) => r !== '/' && !footerLinks.includes(r));

  const pagesDir = path.resolve(__dirname, '../src/pages');
  const pageFiles = (await listFilesRecursive(pagesDir)).filter((p) => p.endsWith('.tsx'));
  const pagesMissingH1: string[] = [];
  for (const file of pageFiles) {
    // ignore layout-only files
    if (file.includes(`${path.sep}layouts${path.sep}`)) continue;
    const src = await fs.readFile(file, 'utf8');
    // Legal pages render h1 inside LegalLayout
    if (src.includes('<LegalLayout')) continue;
    if (!src.includes('<h1')) {
      pagesMissingH1.push(path.relative(path.resolve(__dirname, '..'), file));
    }
  }

  return {
    missingSeo,
    footerLinksNotInRoutes,
    routesNotLinkedInFooter,
    pagesMissingH1,
  };
}

async function main() {
  const result = await audit();

  console.log(`[content-audit] routes=${SITE_ROUTES.length}`);

  if (result.missingSeo.length > 0) {
    console.error('[content-audit] missing SEO (title/description) on:');
    for (const r of result.missingSeo) {
      console.error(`  - ${r.route} :: title=${String(r.title)} desc=${String(r.desc)}`);
    }
    process.exitCode = 1;
  }

  if (result.footerLinksNotInRoutes.length > 0) {
    console.warn('[content-audit] footer links missing from SITE_ROUTES:');
    for (const l of result.footerLinksNotInRoutes) console.warn(`  - ${l}`);
    process.exitCode = 1;
  }

  if (result.routesNotLinkedInFooter.length > 0) {
    console.warn('[content-audit] SITE_ROUTES not linked in footer (excluding /):');
    for (const r of result.routesNotLinkedInFooter) console.warn(`  - ${r}`);
  }

  if (result.pagesMissingH1.length > 0) {
    console.warn('[content-audit] TSX pages missing <h1>:');
    for (const f of result.pagesMissingH1) console.warn(`  - ${f}`);
    process.exitCode = 1;
  }

  console.log('[content-audit] done');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});



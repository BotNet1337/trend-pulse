import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { BLOG_PATH, BLOG_ARTICLES, findArticleByPath } from '../../src/shared/blog/articles';
import { SITE_ROUTES } from '../../src/shared/site/routes';
import { buildHeadTags } from '../../src/shared/seo/seo';
import { SITE } from '../../src/shared/site/constants';

const blogPagesDir = fileURLToPath(new URL('../../src/pages/blog', import.meta.url));
const articlesSourcePath = fileURLToPath(
  new URL('../../src/shared/blog/articles.ts', import.meta.url),
);

function extractTitle(head: string): string | null {
  const m = head.match(/<title>([^<]+)<\/title>/i);
  return m?.[1] ?? null;
}

function extractDescription(head: string): string | null {
  const m = head.match(/<meta name="description" content="([^"]+)"\s*\/>/i);
  return m?.[1] ?? null;
}

function blogSourceFiles(): { file: string; source: string }[] {
  const pageFiles = readdirSync(blogPagesDir)
    .filter((f) => f.endsWith('.tsx') || f.endsWith('.ts'))
    .map((f) => path.join(blogPagesDir, f));
  return [...pageFiles, articlesSourcePath].map((file) => ({
    file,
    source: readFileSync(file, 'utf8'),
  }));
}

test('blog registry: exactly 3 articles, valid slugs, paths under /blog', () => {
  assert.equal(BLOG_ARTICLES.length, 3);
  for (const article of BLOG_ARTICLES) {
    assert.match(article.slug, /^[a-z0-9]+(?:-[a-z0-9]+)*$/, `bad slug: ${article.slug}`);
    assert.equal(article.path, `${BLOG_PATH}/${article.slug}`);
  }
  const paths = BLOG_ARTICLES.map((a) => a.path);
  assert.equal(new Set(paths).size, paths.length, 'article paths must be unique');
});

test('SITE_ROUTES contains /blog and every article path (sitemap + seo:validate coverage)', () => {
  const routes: readonly string[] = SITE_ROUTES;
  assert.ok(routes.includes(BLOG_PATH), 'SITE_ROUTES must include /blog');
  for (const article of BLOG_ARTICLES) {
    assert.ok(routes.includes(article.path), `SITE_ROUTES must include ${article.path}`);
  }
});

test('findArticleByPath resolves each article and rejects unknown paths', () => {
  for (const article of BLOG_ARTICLES) {
    assert.equal(findArticleByPath(article.path)?.slug, article.slug);
  }
  assert.equal(findArticleByPath('/blog/nope'), undefined);
  assert.equal(findArticleByPath('/pricing'), undefined);
});

test('head tags: unique non-empty title/description for /blog and each article', () => {
  const blogRoutes = [BLOG_PATH, ...BLOG_ARTICLES.map((a) => a.path)];
  const titles = new Map<string, string>();
  for (const route of blogRoutes) {
    const head = buildHeadTags(route);
    const title = extractTitle(head);
    const desc = extractDescription(head);
    assert.ok(title && title.length > 0, `missing title for ${route}`);
    assert.ok(desc && desc.length >= 50 && desc.length <= 170, `bad description for ${route}`);
    assert.ok(!titles.has(title), `duplicate title "${title}" (${titles.get(title)} vs ${route})`);
    titles.set(title, route);
  }
  // Blog titles must not collide with existing routes either.
  for (const route of SITE_ROUTES.filter((r: string) => !blogRoutes.includes(r))) {
    const title = extractTitle(buildHeadTags(route));
    assert.ok(title !== null && !titles.has(title), `blog title collides with ${route}`);
  }
});

test('honesty: blog sources contain no forbidden promises (AC3, lesson task-018)', () => {
  const forbidden = [
    /priority scoring/i,
    /AI[ -]powered/i,
    /AI predictions?/i,
    /machine[ -]learning predictions?/i,
    /guaranteed (profit|returns?)/i,
    /financial advice/i,
    /private channels? (monitoring|access)/i,
    /credit card/i, // crypto-only product; "no credit card" copy lives in pricing, not blog claims
  ];
  for (const { file, source } of blogSourceFiles()) {
    for (const pattern of forbidden) {
      assert.ok(
        !pattern.test(source),
        `forbidden phrase ${pattern} found in ${path.basename(file)}`,
      );
    }
  }
});

test('honesty: brand name is never hardcoded in blog sources (config.json is the source)', () => {
  const brand = SITE.brandName;
  assert.ok(brand.length > 0);
  for (const { file, source } of blogSourceFiles()) {
    assert.ok(
      !source.includes(brand),
      `literal brand "${brand}" found in ${path.basename(file)} — use SITE.brandName`,
    );
  }
});

test('honesty: crypto payments article prices come from config.json plans', () => {
  const article = BLOG_ARTICLES.find((a) => a.slug.includes('crypto'));
  assert.ok(article, 'crypto payments article must exist');
  const source = readFileSync(path.join(blogPagesDir, `${article.slug}.tsx`), 'utf8');
  // No hardcoded plan prices: every $NN literal in the article source must be absent;
  // prices must be interpolated from SITE.pricing.plans.
  const hardcodedPrice = source.match(/\$\d+/);
  assert.equal(
    hardcodedPrice,
    null,
    `hardcoded price ${hardcodedPrice?.[0]} in ${article.slug}.tsx — derive from SITE.pricing`,
  );
  assert.ok(
    source.includes('SITE.pricing'),
    'crypto article must reference SITE.pricing for plan prices',
  );
});

test('comparison article: claims about competitors carry a verification date', () => {
  const article = BLOG_ARTICLES.find(
    (a) => a.slug.includes('tgstat') || a.slug.includes('telemetr'),
  );
  assert.ok(article, 'comparison article must exist');
  const source = readFileSync(path.join(blogPagesDir, `${article.slug}.tsx`), 'utf8');
  assert.match(
    source,
    /checked|verified|as of/i,
    'comparison must state when competitor facts were checked',
  );
});

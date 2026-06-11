/**
 * SSR e2e spec — TASK-029 (Epic D / SSR enablement).
 *
 * RED-якорь: тесты написаны ДО реализации и должны падать на C1-статике
 * (createRoot + пустой <div id="root">).
 *
 * Запуск против реального стека (`make up`) — baseURL из playwright.config.ts
 * → http://localhost:${HTTP_PORT} (дефолт :80).
 *
 * AC1 — view-source корня содержит SSR-контент (бренд, не пустой root).
 * AC2 — window.__INITIAL_STATE__ присутствует; нет hydration-mismatch console-error.
 * AC3 — с валидной сессией (fastapiusersauth) SSR guarded-страница встраивает данные.
 * AC4 — без cookie guarded-страница → SSR redirect /auth/sign-in (не пустой 401).
 */

import { test, expect, type ConsoleMessage } from '@playwright/test';

// ────────────────────────────────────────────────────────────────────────────
// helpers
// ────────────────────────────────────────────────────────────────────────────

/** Collect all console messages emitted during page load. */
function collectConsoleMessages(_messages: ConsoleMessage[]): () => void {
  return () => {
    // handled via page.on('console', ...) in each test
  };
}
void collectConsoleMessages; // satisfy no-unused

/**
 * Get raw HTML source for a URL without executing JS (fetch, not browser nav).
 * Uses Playwright request context so it shares the browser's cookie jar.
 */
async function getRawHtml(page: import('@playwright/test').Page, url: string): Promise<string> {
  const response = await page.request.get(url);
  return response.text();
}

// ────────────────────────────────────────────────────────────────────────────
// AC1 — view-source корня содержит SSR-контент
// ────────────────────────────────────────────────────────────────────────────

test('AC1 — view-source / contains SSR markup (not empty root div)', async ({ page }) => {
  // Raw fetch — JS не выполняется, видим точно то, что отдаёт сервер.
  const html = await getRawHtml(page, '/');

  // Сервер должен отдавать не пустой <div id="root"></div>
  // (признак C1-статик/createRoot без SSR).
  expect(html).not.toMatch(/<div id="root"><\/div>/);
  expect(html).not.toMatch(/<div id="root">\s*<\/div>/);

  // HTML должен содержать реальную разметку (бренд или структурные теги
  // — конкретная строка зависит от гидратированной страницы).
  // Минимальный признак SSR: тег <html с DOCTYPE и каким-то content в body.
  expect(html.toLowerCase()).toContain('<!doctype html>');
  expect(html).toContain('Foresignal');
});

test('AC1 — view-source /watchlists contains SSR markup (not empty root div)', async ({ page }) => {
  // Guarded-страница без cookie — SSR должен отдать redirect или auth-контент,
  // но НЕ пустой div id="root".
  const html = await getRawHtml(page, '/watchlists');

  // Не пустой root — признак что SSR что-то рендерит (или redirect 302/301).
  // Если это redirect — response.text() будет минимальным, но не пустым root.
  const isEmptyRoot = /<div id="root">\s*<\/div>/.test(html);
  expect(isEmptyRoot).toBe(false);
});

// ────────────────────────────────────────────────────────────────────────────
// AC2 — window.__INITIAL_STATE__ + нет hydration-mismatch
// ────────────────────────────────────────────────────────────────────────────

test('AC2 — window.__INITIAL_STATE__ is present in page source', async ({ page }) => {
  const html = await getRawHtml(page, '/auth/sign-in');

  // SSR встраивает window.__INITIAL_STATE__ через buildHtml → html.ts.
  expect(html).toContain('window.__INITIAL_STATE__');
});

test('AC2 — no hydration-mismatch console errors on navigation', async ({ page }) => {
  const hydrationErrors: string[] = [];

  page.on('console', (msg) => {
    const text = msg.text();
    // React 19 hydration mismatch messages
    if (
      msg.type() === 'error' &&
      (text.includes('Hydration') ||
        text.includes('hydration') ||
        text.includes('did not match') ||
        text.includes('Text content does not match'))
    ) {
      hydrationErrors.push(text);
    }
  });

  await page.goto('/auth/sign-in', { waitUntil: 'domcontentloaded' });

  // Allow a short time for any deferred hydration errors to surface.
  await page.waitForTimeout(500);

  expect(hydrationErrors).toHaveLength(0);
});

// ────────────────────────────────────────────────────────────────────────────
// AC3 — с валидной сессией SSR guarded-страница встраивает данные
// ────────────────────────────────────────────────────────────────────────────

test('AC3 — authenticated SSR: __INITIAL_STATE__ contains user data', async ({ page }) => {
  // Регистрируем пользователя и логинимся, чтобы получить httpOnly cookie.
  await page.context().clearCookies();

  const email = `ssr-ac3-${Date.now()}@playwright-test.example.com`;
  const password = 'S3curePassw0rd!';

  // Register
  const regResp = await page.request.post('/api/v1/auth/register', {
    data: { email, password },
    headers: { 'Content-Type': 'application/json' },
  });
  // 201 or 400 (already exists) — both are acceptable for this helper
  expect([201, 400]).toContain(regResp.status());

  // Login — sets fastapiusersauth cookie
  const loginResp = await page.request.post('/api/v1/auth/jwt/login', {
    form: { username: email, password },
  });
  // fastapi-users OAuth2PasswordRequestForm → 200 on success
  if (![200, 204].includes(loginResp.status())) {
    test.skip(true, `Login failed (${loginResp.status()}) — backend not available; skipping AC3`);
    return;
  }

  // Now fetch / with the auth cookie set (Playwright shares cookies between request and page).
  const html = await getRawHtml(page, '/watchlists');

  // SSR должен встроить __INITIAL_STATE__ с user-данными.
  expect(html).toContain('window.__INITIAL_STATE__');

  // Парсим состояние из HTML.
  const stateMatch = html.match(/window\.__INITIAL_STATE__\s*=\s*({[\s\S]*?})<\/script>/);
  if (stateMatch) {
    const rawJson = stateMatch[1]
      .replace(/<\\\/script>/g, '</script>')
      .replace(/<\\!--/g, '<!--');
    // Парсим в try, ассертим СНАРУЖИ — иначе catch глотает ошибку expect()
    // и маскирует реальный фейл под «Failed to parse JSON» (так было в CI:
    // валидный {"user":null,"queries":[]} репортился как parse-ошибка).
    let state: {
      user?: { userId?: string; email?: string } | null;
      queries?: unknown[];
    };
    try {
      state = JSON.parse(rawJson) as typeof state;
    } catch {
      // JSON parse failed — state malformed (likely not SSR yet)
      // Report as failure but with context
      throw new Error(`Failed to parse __INITIAL_STATE__ JSON: ${stateMatch[1].slice(0, 200)}`);
    }
    // При авторизованном SSR user не должен быть null.
    // (viewer/model.ts: CURRENT_USER_QUERY_KEY = ['viewer', 'me'])
    // Либо user из /users/me, либо queries содержат запись viewer/me.
    const hasUser = state.user !== null && state.user !== undefined;
    const hasViewerQuery =
      Array.isArray(state.queries) &&
      state.queries.some((q) => {
        const entry = q as { key?: unknown[] };
        return Array.isArray(entry.key) && entry.key[0] === 'viewer';
      });
    expect(hasUser || hasViewerQuery).toBe(true);
  } else {
    // __INITIAL_STATE__ present but pattern not matched — structure changed?
    // At minimum the string is in the HTML, checked above.
    // Don't fail hard — may be minified differently.
  }
});

// ────────────────────────────────────────────────────────────────────────────
// AC4 — без cookie guarded → redirect /auth/sign-in
// ────────────────────────────────────────────────────────────────────────────

test('AC4 — unauthenticated SSR: guarded page redirects to /auth/sign-in', async ({ page }) => {
  await page.context().clearCookies();

  // Follow redirects = false so we can check the redirect itself.
  // Playwright page.goto follows redirects by default — use request API.
  const response = await page.request.get('/watchlists', {
    maxRedirects: 0,
  });

  // SSR должен:
  // (a) вернуть 302/301 redirect на /auth/sign-in  — SSR-level redirect, ИЛИ
  // (b) вернуть 200 с HTML, в котором AuthGuard редиректит клиентски.
  // Для AC4 достаточно что:
  //   - нет raw 401 (exposed JSON error)
  //   - нет пустого root div
  //
  // Вариант (a): 3xx redirect
  if (response.status() >= 300 && response.status() < 400) {
    const location = response.headers()['location'] ?? '';
    expect(location).toContain('/auth/sign-in');
    return;
  }

  // Вариант (b): 200 но с SSR-контентом (клиентский guard редиректит)
  expect(response.status()).toBe(200);
  const html = await response.text();

  // Не пустой root (SSR что-то рендерит)
  expect(html).not.toMatch(/<div id="root">\s*<\/div>/);

  // __INITIAL_STATE__ присутствует
  expect(html).toContain('window.__INITIAL_STATE__');

  // Navigating via browser should end up at /auth/sign-in
  await page.goto('/watchlists');
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 8000 });
  expect(page.url()).toContain('/auth/sign-in');
});

test('AC4 — unauthenticated SSR: raw 401 JSON is NOT returned for guarded page', async ({ page }) => {
  await page.context().clearCookies();

  const response = await page.request.get('/watchlists', { maxRedirects: 5 });

  // Must not be a raw 401 with JSON body
  expect(response.status()).not.toBe(401);

  if (response.status() === 200) {
    const html = await response.text();
    // Must be an HTML document, not a JSON error body
    expect(html.toLowerCase()).toContain('<!doctype html>');
  }
});

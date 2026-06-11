import test from 'node:test';
import assert from 'node:assert/strict';
import { createCasesService, type CasesServiceOptions } from '../../server/cases';

const VALID_ITEM = {
  title: 'Bitcoin ETF approval',
  viral_score: 94.2,
  first_seen: '2026-06-11T14:02:00Z',
  mainstream_at: '2026-06-11T14:45:00Z',
  lead_time_seconds: 2580,
  channels_count: 1,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

type FetchCall = { url: string; signal: AbortSignal | null | undefined };

function makeService(
  overrides: Partial<CasesServiceOptions>,
  responder: (call: FetchCall) => Promise<Response>,
): { service: ReturnType<typeof createCasesService>; calls: FetchCall[] } {
  const calls: FetchCall[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const call: FetchCall = { url: String(input), signal: init?.signal };
    calls.push(call);
    return responder(call);
  };
  const service = createCasesService({
    apiUrl: 'http://api.test/api/v1/cases',
    cacheTtlSeconds: 300,
    fetchTimeoutMs: 2000,
    fetchImpl,
    ...overrides,
  });
  return { service, calls };
}

test('empty apiUrl → [] without any fetch', async () => {
  const { service, calls } = makeService({ apiUrl: '' }, async () =>
    jsonResponse({ items: [VALID_ITEM] }),
  );
  assert.deepEqual(await service.getCases(), []);
  assert.equal(calls.length, 0);
});

test('fetches, validates and returns items; passes an abort signal', async () => {
  const { service, calls } = makeService({}, async () => jsonResponse({ items: [VALID_ITEM] }));
  const items = await service.getCases();
  assert.equal(items.length, 1);
  assert.equal(items[0]?.title, VALID_ITEM.title);
  assert.equal(items[0]?.lead_time_seconds, 2580);
  assert.equal(calls.length, 1);
  assert.ok(calls[0]?.signal instanceof AbortSignal, 'fetch must receive a timeout AbortSignal');
});

test('cache within TTL → repeated calls do not refetch (AC3)', async () => {
  let nowMs = 1_000_000;
  const { service, calls } = makeService({ now: () => nowMs }, async () =>
    jsonResponse({ items: [VALID_ITEM] }),
  );
  await service.getCases();
  nowMs += 299_000; // still inside 300s TTL
  const second = await service.getCases();
  assert.equal(calls.length, 1);
  assert.equal(second.length, 1);
});

test('after TTL expiry → refetches', async () => {
  let nowMs = 1_000_000;
  const { service, calls } = makeService({ now: () => nowMs }, async () =>
    jsonResponse({ items: [VALID_ITEM] }),
  );
  await service.getCases();
  nowMs += 301_000; // past 300s TTL
  await service.getCases();
  assert.equal(calls.length, 2);
});

test('fetch rejection → [] and negative result is cached for TTL (no hammering)', async () => {
  let nowMs = 1_000_000;
  const { service, calls } = makeService({ now: () => nowMs }, async () => {
    throw new Error('connect ECONNREFUSED');
  });
  assert.deepEqual(await service.getCases(), []);
  nowMs += 10_000; // inside TTL
  assert.deepEqual(await service.getCases(), []);
  assert.equal(calls.length, 1);
  nowMs += 300_000; // past TTL — tries again
  await service.getCases();
  assert.equal(calls.length, 2);
});

test('non-2xx response → []', async () => {
  const { service } = makeService({}, async () => jsonResponse({ detail: 'boom' }, 503));
  assert.deepEqual(await service.getCases(), []);
});

test('schema-invalid payload → []', async () => {
  const { service } = makeService({}, async () =>
    jsonResponse({ items: [{ title: 42, viral_score: 'high' }] }),
  );
  assert.deepEqual(await service.getCases(), []);
});

test('non-JSON body → []', async () => {
  const { service } = makeService(
    {},
    async () => new Response('<html>gateway error</html>', { status: 200 }),
  );
  assert.deepEqual(await service.getCases(), []);
});

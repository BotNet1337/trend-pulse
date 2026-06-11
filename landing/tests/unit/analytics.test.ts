/**
 * TASK-068 unit tests — Plausible analytics helper + conditional head tag.
 *
 * track() must be a safe no-op when window/plausible is unavailable (adblock,
 * disabled analytics) — CTA clicks must never break (AC2).
 * buildPlausibleTag() renders the script tag only for a non-empty domain (AC1).
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  track,
  EVENT_SIGN_UP_CLICK,
  EVENT_PRICING_VIEW,
  PLAUSIBLE_SCRIPT_URL,
} from '../../src/shared/analytics/track';
import { buildPlausibleTag, buildHeadTags } from '../../src/shared/seo/seo';

type TestWindow = { plausible?: (event: string) => void };
const globalRef = globalThis as { window?: TestWindow };

test('track: no-op without window (SSR)', () => {
  delete globalRef.window;
  assert.doesNotThrow(() => track(EVENT_SIGN_UP_CLICK));
});

test('track: no-op when window.plausible is missing (blocked script)', () => {
  globalRef.window = {};
  assert.doesNotThrow(() => track(EVENT_SIGN_UP_CLICK));
  delete globalRef.window;
});

test('track: no-op when window.plausible throws', () => {
  globalRef.window = {
    plausible: () => {
      throw new Error('boom');
    },
  };
  assert.doesNotThrow(() => track(EVENT_PRICING_VIEW));
  delete globalRef.window;
});

test('track: forwards the event name to window.plausible', () => {
  const seen: string[] = [];
  globalRef.window = { plausible: (event: string) => seen.push(event) };
  track(EVENT_SIGN_UP_CLICK);
  track(EVENT_PRICING_VIEW);
  assert.deepEqual(seen, ['sign_up_click', 'pricing_view']);
  delete globalRef.window;
});

test('event constants match the Plausible goal names', () => {
  assert.equal(EVENT_SIGN_UP_CLICK, 'sign_up_click');
  assert.equal(EVENT_PRICING_VIEW, 'pricing_view');
});

test('buildPlausibleTag: empty domain renders nothing', () => {
  assert.equal(buildPlausibleTag(''), null);
});

test('buildPlausibleTag: non-empty domain renders one deferred script tag', () => {
  const tag = buildPlausibleTag('foresignal.biz');
  assert.ok(tag, 'tag must be rendered');
  assert.match(tag, /<script defer /);
  assert.match(tag, /data-domain="foresignal\.biz"/);
  assert.ok(tag.includes(`src="${PLAUSIBLE_SCRIPT_URL}"`));
});

test('buildHeadTags: contains exactly one Plausible tag for every route (config domain set)', () => {
  for (const path of ['/', '/pricing', '/cookie-policy', '/some-404']) {
    const head = buildHeadTags(path);
    const matches = head.match(/plausible\.io\/js\/script\.js/g) ?? [];
    assert.equal(matches.length, 1, `expected exactly one plausible tag on ${path}`);
  }
});

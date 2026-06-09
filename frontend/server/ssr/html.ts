import type { FastifyBaseLogger } from 'fastify';
import type { RenderPayload } from './ssr.types.ts';

export interface BuildHtmlOptions {
  /**
   * Per-request CSP nonce produced by `@fastify/helmet`. Stamped on the
   * inline `__INITIAL_STATE__` script so CSP `script-src` does not need
   * `'unsafe-inline'`. Pass `undefined` only in non-production environments
   * where helmet may be skipped.
   */
  cspNonce?: string;
  logger?: FastifyBaseLogger;
}

const INITIAL_STATE_WARN_BYTES = 100 * 1024;

const escapeForScript = (value: string): string =>
  // Prevent `</script>` in the JSON payload from breaking out of the inline
  // script tag, and avoid HTML comment confusion. JSON.stringify already
  // escapes quotes/backslashes; only these tokens need extra handling.
  value.replace(/<\/(script)/gi, '<\\/$1').replace(/<!--/g, '<\\!--');

/**
 * Adds `nonce="${nonce}"` to every `<script>` tag that doesn't already have
 * one. Required because helmet's CSP runs once per response and only knows
 * about inline scripts at HTML build time — but our SSR pipeline emits
 * inline `<script>` from TanStack Router (`payload.injectedScripts`) and
 * from the static `index.html` template. Without the nonce these get
 * CSP-blocked.
 */
const stampNonce = (html: string, nonce: string): string =>
  html.replace(/<script(?![^>]*\bnonce=)([^>]*)>/g, `<script nonce="${nonce}"$1>`);

export function buildHtml(
  template: string,
  payload: RenderPayload,
  options: BuildHtmlOptions = {},
): string {
  const stateJson = JSON.stringify(payload.initialState);
  if (stateJson.length > INITIAL_STATE_WARN_BYTES) {
    options.logger?.warn(
      { sizeBytes: stateJson.length },
      `__INITIAL_STATE__ exceeds ${INITIAL_STATE_WARN_BYTES} bytes — consider pruning prefetch composition`,
    );
  }
  const serializedState = escapeForScript(stateJson);
  const nonceAttr = options.cspNonce ? ` nonce="${options.cspNonce}"` : '';
  const initialStateScript = `<script${nonceAttr}>window.__INITIAL_STATE__=${serializedState}</script>`;

  const appHtml = payload.html.trim();
  const scripts = payload.injectedScripts || '';

  const merged = template
    .replace('<!--app-html-->', appHtml)
    .replace(
      '<!--initial-state-->',
      `${initialStateScript}\n${scripts}`
    );

  return options.cspNonce ? stampNonce(merged, options.cspNonce) : merged;
}

import type { AppConfig } from './config.js';
import type { TransformMap } from './types.js';

export function mergePreviewQuery(
  defaults: Record<string, unknown>,
  query: Record<string, string | string[] | undefined>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...defaults };
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    const v = Array.isArray(value) ? value[0] : value;
    if (typeof v === 'string') {
      out[key] = v;
    }
  }
  return out;
}

function resolveValue(
  path: string,
  payload: Record<string, unknown>,
): unknown {
  const parts = path.split('.');
  let current: unknown = payload;

  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined;
    if (!(part in current)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }

  return current;
}

export function interpolate(
  template: string,
  payload: Record<string, unknown>,
  config: AppConfig,
): string {
  return template.replace(
    /\{\{([^}]+)\}\}/g,
    (_, expr: string) => {
      const segments = expr.trim().split('|').map((s: string) => s.trim());
      const path = segments[0] ?? '';
      const pipes = segments.slice(1);

      let value = resolveValue(path, payload);

      if (value === undefined && path in config) {
        value = config[path as keyof AppConfig];
      }

      let result = value != null ? String(value) : '';

      for (const pipe of pipes) {
        if (pipe === 'urlencode') {
          result = encodeURIComponent(result);
        } else if (pipe === 'uppercase') {
          result = result.toUpperCase();
        } else if (pipe === 'lowercase') {
          result = result.toLowerCase();
        } else if (pipe === 'capitalize') {
          result = result.charAt(0).toUpperCase() + result.slice(1);
        } else if (pipe === 'emailprefix') {
          const at = result.indexOf('@');
          if (at > 0) result = result.slice(0, at);
        } else if (pipe === 'date') {
          const d = new Date(result);
          if (!isNaN(d.getTime())) {
            result = d.toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            });
          }
        } else if (pipe === 'time') {
          const d = new Date(result);
          if (!isNaN(d.getTime())) {
            result = d.toLocaleTimeString('en-US', {
              hour: '2-digit',
              minute: '2-digit',
            });
          }
        } else if (pipe === 'datetime') {
          const d = new Date(result);
          if (!isNaN(d.getTime())) {
            result = d.toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            });
          }
        } else if (pipe.startsWith('default:')) {
          if (result === '') {
            result = pipe.slice(8);
          }
        } else if (pipe.startsWith('truncate:')) {
          const max = parseInt(pipe.slice(9), 10);
          if (!isNaN(max) && result.length > max) {
            result = result.slice(0, max) + '…';
          }
        }
      }

      return result;
    },
  );
}

export function applyTransform(
  transformMap: TransformMap | null,
  payload: Record<string, unknown>,
  config: AppConfig,
): Record<string, unknown> {
  if (!transformMap) return payload;

  const result: Record<string, unknown> = {};
  for (const [key, template] of Object.entries(transformMap)) {
    result[key] = interpolate(template, payload, config);
  }
  return result;
}

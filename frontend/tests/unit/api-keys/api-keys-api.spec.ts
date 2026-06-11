/**
 * Unit tests: api-keys API module (TASK-065).
 *
 * Mocks apiClient to verify paths/methods/data-unwrap without network.
 * No jsdom — vitest runs in node environment; component rendering is
 * covered by e2e (project pattern: @testing-library/react not installed).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import { apiClient } from '@/shared/api/client';
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
} from '../../../src/features/api-keys/api';

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);
const mockedDelete = vi.mocked(apiClient.delete);

beforeEach(() => {
  vi.clearAllMocks();
});

describe('api-keys API layer', () => {
  it('listApiKeys GETs /api-keys and unwraps data', async () => {
    const rows = [
      {
        id: 1,
        name: 'prod',
        prefix: 'tp_abc12345',
        created_at: '2026-06-11T00:00:00Z',
        last_used_at: null,
        revoked_at: null,
      },
    ];
    mockedGet.mockResolvedValueOnce({ data: rows });

    const result = await listApiKeys();

    expect(mockedGet).toHaveBeenCalledWith('/api-keys');
    expect(result).toEqual(rows);
  });

  it('createApiKey POSTs /api-keys with {name} body and unwraps ApiKeyCreated', async () => {
    const created = {
      id: 2,
      name: 'ci',
      prefix: 'tp_def67890',
      key: 'tp_def67890_plaintext',
      created_at: '2026-06-11T00:00:00Z',
    };
    mockedPost.mockResolvedValueOnce({ data: created });

    const result = await createApiKey('ci');

    expect(mockedPost).toHaveBeenCalledWith('/api-keys', { name: 'ci' });
    expect(result).toEqual(created);
  });

  it('revokeApiKey DELETEs /api-keys/{id}', async () => {
    mockedDelete.mockResolvedValueOnce({ data: undefined });

    await revokeApiKey(7);

    expect(mockedDelete).toHaveBeenCalledWith('/api-keys/7');
  });

  it('listApiKeys propagates errors (no swallowing)', async () => {
    mockedGet.mockRejectedValueOnce(new Error('boom'));
    await expect(listApiKeys()).rejects.toThrow('boom');
  });
});

describe('api-keys query key', () => {
  it('API_KEYS_QUERY_KEY is the stable ["api-keys"] tuple', async () => {
    // Dynamic import: we only need the exported constant, not React hooks.
    const mod = await import('../../../src/features/api-keys/queries');
    expect(mod.API_KEYS_QUERY_KEY).toEqual(['api-keys']);
  });
});

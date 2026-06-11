/**
 * Unit tests: delete-account dialog copy (TASK-072 AC4).
 *
 * Компонент не рендерим (node env, без testing-library) — копия вынесена в
 * константу copy.ts, ассертим её напрямую: описание говорит про реальные
 * сущности TrendPulse-аккаунта (watchlists / alerts / subscription) и не
 * упоминает workspaces/posts из чужого проекта.
 */

import { describe, it, expect } from 'vitest';
import { DELETE_ACCOUNT_DESCRIPTION } from '../../../src/features/account/delete/ui/copy';

describe('delete-account dialog copy', () => {
  it('describes the real deletion cascade: account, watchlists, alerts, subscription', () => {
    expect(DELETE_ACCOUNT_DESCRIPTION).toContain('account');
    expect(DELETE_ACCOUNT_DESCRIPTION).toContain('watchlists');
    expect(DELETE_ACCOUNT_DESCRIPTION).toContain('alerts');
    expect(DELETE_ACCOUNT_DESCRIPTION).toContain('subscription');
    expect(DELETE_ACCOUNT_DESCRIPTION).toContain('cannot be undone');
  });

  it('does not mention foreign-project entities (workspaces/posts)', () => {
    expect(DELETE_ACCOUNT_DESCRIPTION.toLowerCase()).not.toContain('workspace');
    expect(DELETE_ACCOUNT_DESCRIPTION.toLowerCase()).not.toContain('post');
  });

  it('contains no Cyrillic (EN-only product, AC1)', () => {
    expect(DELETE_ACCOUNT_DESCRIPTION).not.toMatch(/[А-Яа-яЁё]/);
  });
});

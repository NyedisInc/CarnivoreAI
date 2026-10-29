import { beforeEach, describe, expect, test, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch }));

import { forkSessionTo, forkToBody } from './fork-to';

beforeEach(() => authFetch.mockClear());

describe('fork-to', () => {
  test('a body leaves out every blank optional field and trims the rest', () => {
    expect(forkToBody({ provider: 'codex', model: '  ', effort: '', prompt: '', name: ' kid ', worktree: false })).toEqual({
      to_provider: 'codex', name: 'kid', worktree: false,
    });
  });

  test('forkSessionTo posts that body to the encoded session route', async () => {
    await forkSessionTo('ses a/b', { provider: 'claude', model: 'm', effort: 'high', prompt: 'go', name: '', worktree: true });
    expect(authFetch).toHaveBeenCalledWith('/sessions/ses%20a%2Fb/fork-to', {
      method: 'POST',
      body: JSON.stringify({ to_provider: 'claude', model: 'm', effort: 'high', prompt: 'go', worktree: true }),
    });
  });
});

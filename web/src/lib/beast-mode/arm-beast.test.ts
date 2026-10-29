import { beforeEach, describe, expect, test, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch }));

import { armBeast, BEAST_ROUTE } from './control.svelte';

beforeEach(() => authFetch.mockClear());

describe('armBeast', () => {
  test('writes enabled, the prompts scope and the auto-off hours in one PUT', async () => {
    await armBeast(true, 4);
    expect(authFetch).toHaveBeenCalledWith(BEAST_ROUTE, { method: 'PUT', body: JSON.stringify({ enabled: true, prompts: true, hours: 4 }) });
  });

  test('until turned off is null, and a refusal reaches the caller', async () => {
    await armBeast(false, null);
    expect(authFetch).toHaveBeenLastCalledWith(BEAST_ROUTE, { method: 'PUT', body: JSON.stringify({ enabled: true, prompts: false, hours: null }) });
    authFetch.mockRejectedValueOnce(new Error('no'));
    await expect(armBeast(false, null)).rejects.toThrow('no');
  });
});

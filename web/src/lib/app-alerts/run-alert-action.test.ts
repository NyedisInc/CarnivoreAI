import { beforeEach, describe, expect, test, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()), authFetch }));

import { runAlertAction } from './alerts.svelte';

beforeEach(() => authFetch.mockClear());

describe('runAlertAction', () => {
  test('defaults to GET with no body', async () => {
    await runAlertAction({ id: 'open', label_key: 'k', route: '/alerts/3' });
    expect(authFetch).toHaveBeenCalledWith('/api/v1/alerts/3', { method: 'GET' });
  });

  test('sends the named method upper-cased with its JSON body, and a refusal reaches the caller', async () => {
    await runAlertAction({ id: 'recheck', label_key: 'k', method: 'post', route: '/alerts/3/recheck', body: { now: true } });
    expect(authFetch).toHaveBeenCalledWith('/api/v1/alerts/3/recheck', { method: 'POST', body: JSON.stringify({ now: true }) });
    authFetch.mockRejectedValueOnce(new Error('down'));
    await expect(runAlertAction({ id: 'x', label_key: 'k', route: '/x' })).rejects.toThrow('down');
  });
});

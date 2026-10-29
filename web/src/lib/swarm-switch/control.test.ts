import { afterEach, describe, expect, test, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch }));
vi.mock('../../opscenter/api/poll.svelte', () => ({ resource: vi.fn() }));

import { swarmSwitch, toggleSwarm } from './control.svelte';

afterEach(() => {
  swarmSwitch.data = null;
  authFetch.mockReset();
});

describe('toggleSwarm', () => {
  test('on flips to off with one PUT and holds the server answer', async () => {
    swarmSwitch.data = { enabled: true };
    authFetch.mockResolvedValueOnce({ enabled: false });
    await toggleSwarm();
    expect(authFetch).toHaveBeenCalledTimes(1);
    expect(authFetch.mock.calls[0]![0]).toBe('/swarm/switch');
    expect(authFetch.mock.calls[0]![1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ enabled: false }) });
    expect(swarmSwitch.data).toEqual({ enabled: false });
  });

  test('a refused write keeps the state the server last said', async () => {
    swarmSwitch.data = { enabled: false };
    authFetch.mockRejectedValueOnce(new Error('config.json could not be updated'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    await toggleSwarm();
    expect(swarmSwitch.data).toEqual({ enabled: false });
    warn.mockRestore();
  });

  test('NEGATIVE: an unknown state sends nothing', async () => {
    await toggleSwarm();
    expect(authFetch).not.toHaveBeenCalled();
  });
});

/** @vitest-environment jsdom */
import { flushSync, tick } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch }));
vi.mock('../../opscenter/api/poll.svelte', () => ({ resource: vi.fn() }));

import { resource } from '../../opscenter/api/poll.svelte';
import { seedSwarmSwitch, startSwarmSwitch, swarmSwitch, toggleSwarm, type SwarmSwitchStatus } from './control.svelte';

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

  test('an explicit next is what is sent, not the opposite of a stale store', async () => {
    swarmSwitch.data = { enabled: true };
    authFetch.mockResolvedValueOnce({ enabled: true });
    await toggleSwarm(true);
    expect(authFetch.mock.calls[0]![1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ enabled: true }) });
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

describe('startSwarmSwitch follows the read, and the read alone, in the real app', () => {
  const answer = new SvelteMap<string, SwarmSwitchStatus | null>();
  beforeAll(() => {
    vi.mocked(resource).mockReturnValue({ get data() { return answer.get('d') ?? null; } } as never);
    startSwarmSwitch();
  });

  test('an answer is copied into the store', async () => {
    answer.set('d', { enabled: true });
    flushSync();
    await tick();
    expect(swarmSwitch.data).toEqual({ enabled: true });
  });

  test('sign-out (dropRows empties the read) clears the store, so the next user never sees the last one\'s state', async () => {
    answer.set('d', { enabled: true });
    flushSync();
    await tick();
    answer.set('d', null);
    flushSync();
    await tick();
    expect(swarmSwitch.data).toBeNull();
  });

  test('a seeded state (the style guide) stays while the read has no answer', async () => {
    seedSwarmSwitch({ enabled: true });
    answer.set('d', { enabled: false });
    flushSync();
    await tick();
    answer.set('d', null);
    flushSync();
    await tick();
    expect(swarmSwitch.data).toEqual({ enabled: true });
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const calls: Array<{ path: string; method: string; body: unknown }> = [];
let answers: unknown[] = [];

vi.mock('./auth.svelte', () => ({
  authFetch: (path: string, init: RequestInit = {}) => {
    calls.push({
      path,
      method: (init.method ?? 'GET').toUpperCase(),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
    });
    return Promise.resolve(answers.shift());
  },
}));

vi.mock('./poll.svelte', () => ({ resource: () => ({ data: [], refresh: async () => {} }) }));

const NEEDED = {
  status: 'refused',
  code: 'wrapper_needed',
  detail: "'claude' is not a configured launch wrapper",
  wrapper_options: ['claude-skip-permissions', 'cld'],
};

type Mod = typeof import('./asleep.svelte');

async function load(): Promise<Mod> {
  vi.resetModules();
  calls.length = 0;
  answers = [];
  return import('./asleep.svelte');
}

describe('waking an asleep session', () => {
  beforeEach(() => {
    delete (globalThis as Record<string, unknown>).SessionRowMenuSleep;
  });
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).SessionRowMenuSleep;
  });

  it('sends a picked wrapper as agent_type, and nothing when none was picked', async () => {
    const mod = await load();
    answers = [{ status: 'started', detail: '' }, { status: 'started', detail: '' }];
    await mod.wakeSession('u-1');
    await mod.wakeSession('u-1', 'cld');
    expect(calls).toEqual([
      { path: '/sessions/u-1/wake', method: 'POST', body: null },
      { path: '/sessions/u-1/wake', method: 'POST', body: { agent_type: 'cld' } },
    ]);
  });

  it('opens the picker on wrapper_needed and returns the pick\'s answer', async () => {
    const mod = await load();
    answers = [NEEDED];
    const pickAndWake = vi.fn(async () => ({ status: 'started', detail: 'resumed' }));
    (globalThis as Record<string, unknown>).SessionRowMenuSleep = { pickAndWake };
    const out = await mod.wakeOrPick('u-3d', 'carnivore_3D Work-2', '3D Work');
    expect(pickAndWake).toHaveBeenCalledWith('carnivore_3D Work-2', '3D Work', 'u-3d');
    expect(out).toEqual({ status: 'started', detail: 'resumed' });
  });

  it('a cancelled pick is null, so nothing is reported as a failure', async () => {
    const mod = await load();
    answers = [NEEDED];
    (globalThis as Record<string, unknown>).SessionRowMenuSleep = { pickAndWake: async () => null };
    expect(await mod.wakeOrPick('u', 'n', 'l')).toBeNull();
  });

  it('with no picker on the page the refusal comes back with its sentence', async () => {
    const mod = await load();
    answers = [NEEDED];
    expect(await mod.wakeOrPick('u', 'n', 'l')).toEqual(NEEDED);
  });

  it('a started wake or another refusal never opens the picker', async () => {
    const mod = await load();
    const pickAndWake = vi.fn();
    (globalThis as Record<string, unknown>).SessionRowMenuSleep = { pickAndWake };
    answers = [{ status: 'started', detail: '' }, { status: 'refused', detail: 'transcript gone' }];
    expect((await mod.wakeOrPick('u', 'n', 'l'))?.status).toBe('started');
    expect((await mod.wakeOrPick('u', 'n', 'l'))?.detail).toBe('transcript gone');
    expect(pickAndWake).not.toHaveBeenCalled();
  });
});

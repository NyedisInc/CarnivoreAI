import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SessionInfo } from './types';

let wakeFailure: unknown = null;
const reach = vi.hoisted(() => vi.fn());

vi.mock('./auth.svelte', () => ({
  authFetch: () => (wakeFailure ? Promise.reject(wakeFailure) : Promise.resolve({ status: 'started', detail: '' })),
}));
vi.mock('./poll.svelte', () => ({ resource: () => ({ data: [], refresh: async () => {} }) }));
vi.mock('./sessions.svelte', () => ({ reachWokenSession: reach }));

function apiError(status: number, code: string | null, message = 'server sentence'): Error {
  return Object.assign(new Error(message), { status, code });
}

function legacyError(status: number, code: string, message = 'server sentence'): Error {
  return Object.assign(new Error(message), { status, detail: { code, detail: message }, body: { detail: { code, detail: message } } });
}

const live = { session_row_id: 7, session_uuid: 'u7', session: { id: 'ses_live' } } as unknown as SessionInfo;

type Asleep = typeof import('./asleep.svelte');
type Answer = typeof import('./wake-answer');

async function load(): Promise<{ asleep: Asleep; answer: Answer }> {
  vi.resetModules();
  return { asleep: await import('./asleep.svelte'), answer: await import('./wake-answer') };
}

beforeEach(() => {
  wakeFailure = null;
  reach.mockReset();
});

describe('wakeOrPick on a not-asleep refusal', () => {
  it('answers started with the live session id when the list carries the row', async () => {
    const { asleep } = await load();
    wakeFailure = apiError(409, 'session_not_asleep');
    reach.mockResolvedValue(live);
    const result = await asleep.wakeOrPick('u7', 'carnivore_a', 'a');
    expect(result).toMatchObject({ status: 'started', session_id: 'ses_live' });
    expect(reach).toHaveBeenCalledWith('u7');
  });

  it('rejects with the server sentence when the list never carries the row', async () => {
    const { asleep } = await load();
    wakeFailure = apiError(409, 'session_not_asleep', 'this session is not asleep, so there is nothing to wake.');
    reach.mockResolvedValue(null);
    await expect(asleep.wakeOrPick('u7', 'carnivore_a', 'a')).rejects.toThrow('this session is not asleep');
  });

  it.each([
    ['another 409 code', 409, 'restart_in_progress'],
    ['a 404', 404, null],
    ['a 500', 500, null],
    ['a 503', 503, 'datastore_unavailable'],
    ['code text on the wrong status', 400, 'session_not_asleep'],
  ])('%s still rejects and never reads the list', async (_label, status, code) => {
    const { asleep } = await load();
    wakeFailure = apiError(status, code);
    await expect(asleep.wakeOrPick('u7', 'carnivore_a', 'a')).rejects.toThrow('server sentence');
    expect(reach).not.toHaveBeenCalled();
  });

  it('a plain started answer waits for the row to reach the list', async () => {
    const { asleep } = await load();
    reach.mockResolvedValue(live);
    const result = await asleep.wakeOrPick('u7', 'carnivore_a', 'a');
    expect(result?.status).toBe('started');
    expect(reach).toHaveBeenCalledWith('u7');
  });
});

describe('liveRowAfterNotAsleep, for the callers that use the legacy client', () => {
  it('reads the legacy error shape by code, never by message text', async () => {
    const { answer } = await load();
    const reachFake = vi.fn().mockResolvedValue(live);
    expect(await answer.liveRowAfterNotAsleep(legacyError(409, 'session_not_asleep', 'any words'), 'u7', reachFake)).toBe(live);
    expect(await answer.liveRowAfterNotAsleep(legacyError(409, 'restart_in_progress', 'this session is not asleep'), 'u7', reachFake)).toBeNull();
    expect(reachFake).toHaveBeenCalledTimes(1);
  });

  it('is null for a non-error, a missing uuid and a 409 with no code', async () => {
    const { answer } = await load();
    const reachFake = vi.fn().mockResolvedValue(live);
    expect(await answer.liveRowAfterNotAsleep(null, 'u7', reachFake)).toBeNull();
    expect(await answer.liveRowAfterNotAsleep(apiError(409, 'session_not_asleep'), '', reachFake)).toBeNull();
    expect(await answer.liveRowAfterNotAsleep(apiError(409, null), 'u7', reachFake)).toBeNull();
    expect(reachFake).not.toHaveBeenCalled();
  });
});

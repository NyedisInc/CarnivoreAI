/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let ops: Record<string, unknown>[] = [];
let cancelRefusal: string | null = null;
const posts: string[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => {
  const real = await original<Record<string, unknown>>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string }) => {
      if (init?.method === 'POST') {
        posts.push(path);
        if (cancelRefusal) throw new (real.ApiError as new (m: string, s: number, c: string | null, p: unknown) => Error)(cancelRefusal, 409, null, { detail: { code: 'past_point_of_no_return', detail: cancelRefusal } });
        return { op_id: 'op1', state: 'cancelling' };
      }
      return { ops };
    },
  };
});

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import PackOpToast from './PackOpToast.svelte';
import { packOps, view } from './pack-op-store.svelte';

setLocale('en');

const op = (over: Record<string, unknown> = {}) => ({
  id: 'op1', kind: 'session', direction: 'out', name: 'Tetra', machine: 'hosta', mode: 'move', state: 'waiting', step: 'wait',
  steps: ['check', 'wait', 'sleep', 'carry', 'wake', 'forward'], error_code: null, error: null, started_at: new Date(Date.now() - 65000).toISOString(),
  finished_at: null, session_uuid: 'u1', target_session_uuid: 'u1', claude_session_uuid: 'c1', wait_until: null, waiting_on: null, agents: null, shells: null, running: true, interrupted: false,
  cancellable: true, cancel_blocked: null, ...over,
});

const mounted: ReturnType<typeof mount>[] = [];
async function show(list: Record<string, unknown>[]): Promise<HTMLElement> {
  ops = list;
  await packOps.refresh(true);
  flushSync();
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PackOpToast, { target }));
  flushSync();
  return target;
}
const q = (sel: string) => document.querySelector<HTMLElement>(sel);
const settle = async () => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };

beforeEach(() => { auth.state = 'signed-in'; posts.length = 0; cancelRefusal = null; view.dismissed = []; view.note = {}; view.folded = {}; view.cancelling = {}; });
afterEach(async () => { for (const m of mounted.splice(0)) await unmount(m); document.body.replaceChildren(); });

describe('pack transfer status toast', () => {
  test('running: names what moves where, the step and elapsed time, and cancel posts to the cancel route', async () => {
    await show([op()]);
    expect(q('[data-pot="title"]')!.textContent).toBe('moving Tetra to hosta');
    expect(q('[data-pot="step"]')!.textContent).toContain("waiting for the agent's turn to end");
    expect(q('[data-pot="time"]')!.textContent).toMatch(/^1:0\d$/);
    expect(q('[data-pot="dismiss"]')).toBeNull();
    q('[data-pot="cancel"]')!.click();
    await settle();
    expect(posts).toEqual(['/pack/ops/op1/cancel']);
  });

  test('a project move waiting on its agents says how many', async () => {
    await show([op({ kind: 'project', step: 'wait', agents: 3 })]);
    expect(q('[data-pot="step"]')!.textContent).toContain('waiting for 3 agents to finish their turns');
  });

  test('the shell stop step reads how many background shells it is stopping', async () => {
    await show([op({ step: 'stop_shells', shells: 2 })]);
    expect(q('[data-pot="step"]')!.textContent).toBe('stopping 2 background shells');
  });

  test('a cancel past the point of no return shows the server reason and the card keeps running', async () => {
    cancelRefusal = 'the other computer is already starting the agent, so it can no longer be stopped';
    await show([op({ step: 'wake' })]);
    q('[data-pot="cancel"]')!.click();
    await settle();
    expect(q('[data-pot="note"]')!.textContent).toBe(cancelRefusal);
    expect(q('[data-phase="running"]')).not.toBeNull();
  });

  test('canceled, done and failed all stay until dismissed, then the card goes', async () => {
    const done = { running: false, finished_at: new Date().toISOString() };
    await show([
      op({ id: 'a', ...done, state: 'failed', error_code: 'cancelled' }),
      op({ id: 'b', ...done, state: 'moved', step: 'forward' }),
      op({ id: 'c', ...done, state: 'failed', error_code: 'turn_not_ended', error: 'Tetra still has 2 background shells running; stop them, then send again' }),
    ]);
    expect(q('[data-op="a"] [data-pot="outcome"]')!.textContent).toBe('canceled. Tetra is still here, exactly as it was.');
    expect(q('[data-op="b"] [data-pot="title"]')!.textContent).toBe('Tetra is now on hosta');
    expect(q('[data-op="c"] [data-pot="outcome"]')!.textContent).toBe('Tetra still has 2 background shells running; stop them, then send again');
    expect(q('[data-op="c"]')!.getAttribute('role')).toBe('alert');
    q('[data-op="b"] [data-pot="dismiss"]')!.click();
    flushSync();
    expect(q('[data-op="b"]')).toBeNull();
    expect(document.querySelectorAll('[data-op]')).toHaveLength(2);
  });
});

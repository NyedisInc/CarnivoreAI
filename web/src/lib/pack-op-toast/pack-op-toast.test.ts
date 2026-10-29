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
  id: 'op1', kind: 'session', direction: 'out', name: 'DrMario', machine: 'studio', mode: 'move', state: 'waiting', step: 'wait',
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

beforeEach(() => { auth.state = 'signed-in'; posts.length = 0; cancelRefusal = null; view.dismissed = []; view.note = {}; view.folded = {}; view.details = {}; view.cancelling = {}; });
afterEach(async () => { for (const m of mounted.splice(0)) await unmount(m); document.body.replaceChildren(); });

describe('pack transfer status toast', () => {
  test('running: names what moves where, the step and elapsed time, and cancel posts to the cancel route', async () => {
    await show([op()]);
    expect(q('[data-pot="title"]')!.textContent).toBe('moving DrMario to studio');
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
      op({ id: 'c', ...done, state: 'failed', error_code: 'turn_not_ended', error: 'DrMario still has 2 background shells running; stop them, then send again' }),
    ]);
    expect(q('[data-op="a"] [data-pot="outcome"]')!.textContent).toBe('canceled. DrMario is still here, exactly as it was.');
    expect(q('[data-op="b"] [data-pot="title"]')!.textContent).toBe('DrMario is now on studio');
    expect(q('[data-op="c"] [data-pot="outcome"]')!.textContent).toBe('DrMario still has 2 background shells running; stop them, then send again');
    expect(q('[data-op="c"]')!.getAttribute('role')).toBe('alert');
    q('[data-op="b"] [data-pot="dismiss"]')!.click();
    flushSync();
    expect(q('[data-op="b"]')).toBeNull();
    expect(document.querySelectorAll('[data-op]')).toHaveLength(2);
  });

  test('a step with bytes draws the bar, the size and the ETA, and details opens the log', async () => {
    const progress = { step: 'carry', bytes_done: 1048576, bytes_total: 4194304, rate: 524288, eta_s: 360, log: [{ at: 1700000000, step: 'carry', text: 'step carry started' }] };
    await show([op({ step: 'carry', progress })]);
    expect(q('[data-pot="bar"]')!.getAttribute('aria-valuenow')).toBe('54');
    expect(q('[data-pot="meta"]')!.textContent).toBe('1.0 mb of 4.0 mb, 512.0 kb a second, about 6m left');
    expect(q('[data-pot="log"]')).toBeNull();
    q('[data-pot="details"]')!.click();
    flushSync();
    expect(q('[data-pot="log"]')!.textContent).toContain('carry step carry started');
  });

  test('a step with no bytes shows the step bar alone, no size and no ETA', async () => {
    await show([op({ step: 'wait', progress: null })]);
    expect(q('[data-pot="bar"]')!.getAttribute('aria-valuenow')).toBe('17');
    expect(q('[data-pot="meta"]')).toBeNull();
  });

  test('a middle click dismisses a finished card like its dismiss button, cancels autoscroll, and leaves a running card alone (#2680)', async () => {
    await show([op()]);
    const running = q('[data-op="op1"]')!;
    running.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true }));
    flushSync();
    expect(q('[data-op="op1"]')).not.toBeNull();
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
    await show([op({ running: false, state: 'done', finished_at: new Date().toISOString() })]);
    const card = q('[data-op="op1"]')!;
    const down = new MouseEvent('mousedown', { button: 1, bubbles: true, cancelable: true });
    card.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    const left = new MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true });
    card.dispatchEvent(left);
    expect(left.defaultPrevented).toBe(false);
    card.dispatchEvent(new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true }));
    flushSync();
    expect(q('[data-op="op1"]')).toBeNull();
  });
});

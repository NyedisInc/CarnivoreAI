/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
let reply: unknown = null;
let fail = false;

vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetch: async (path: string) => {
    calls.push(path);
    if (fail) throw new Error('server said no');
    return reply;
  },
}));

import SubagentBadge from './SubagentBadge.svelte';
import { closeSubagentList, openSubagentList, SUBAGENT_LIST_ID } from './popup';
import { emptyMessage, measuredRunningTotal, orderRows, runningCount, runningTotal, type SessionSubagents } from './subagents';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  calls.length = 0;
  fail = false;
  reply = null;
});

afterEach(async () => {
  closeSubagentList();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function render(props: Record<string, unknown>): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(SubagentBadge, { target, props: props as never }));
  flushSync();
  return target;
}

function payload(over: Partial<SessionSubagents> = {}): SessionSubagents {
  return {
    state: 'ok',
    family: 'claude',
    conversation_uuid: 'u',
    counts: { total: 3, listed: 3, running: 1, done: 1, unknown: 1, shape_unrecognized: 0, internal: 0 },
    subagents: [
      { id: 'a1', agent_type: 'worker', description: 'finished thing', model: null, background: false,
        spawn_depth: 1, started_at: '2026-09-26T10:00:00Z', last_activity_at: '2026-09-26T10:05:00Z',
        status: 'done', status_reason: 'end_recorded', end_status: 'completed' },
      { id: 'a2', agent_type: 'Explore', description: 'still going', model: null, background: true,
        spawn_depth: 1, started_at: '2026-09-26T11:00:00Z', last_activity_at: '2026-09-26T11:59:00Z',
        status: 'running', status_reason: 'no_end_recorded', end_status: null },
      { id: 'a3', agent_type: null, description: null, model: null, background: null,
        spawn_depth: null, started_at: null, last_activity_at: null,
        status: 'unknown', status_reason: 'silent', end_status: null },
    ],
    detail: '',
    as_of: null,
    ...over,
  };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

test('no chip for a null, absent, zero or negative count', () => {
  for (const running of [null, undefined, 0, -1, Number.NaN]) {
    const root = render({ running, sessionId: 's' });
    expect(root.querySelector('.subagent-count')).toBeNull();
  }
  expect(render({ running: 2, total: 5, sessionId: 's' }).querySelector('.subagent-count')).not.toBeNull();
});

test('the chip says the running count and the full sentence', () => {
  const button = render({ running: 2, total: 5, sessionId: 's' }).querySelector('button')!;
  expect(button.textContent).toBe('2 sub');
  expect(button.getAttribute('aria-label')).toBe('2 subagents running, 5 launched in this conversation');
  expect(button.classList.contains('subagent-count--button')).toBe(true);
});

test('a rollup is a plain sum, not a control', () => {
  const root = render({ running: 3, rollup: true, rollupTitle: 'three' });
  expect(root.querySelector('button')).toBeNull();
  const chip = root.querySelector('[data-subagents-rollup]')!;
  expect(chip.textContent).toBe('3 sub');
  expect(chip.getAttribute('title')).toBe('three');
});

test('a click opens the list, reads the route once, and does not reach the row', async () => {
  reply = payload();
  const row = document.createElement('div');
  const rowClicks = vi.fn();
  row.addEventListener('click', rowClicks);
  document.body.append(row);
  const target = document.createElement('div');
  row.append(target);
  mounted.push(mount(SubagentBadge, { target, props: { running: 1, total: 3, sessionId: 'adopted:x y', name: 'api work' } }));
  flushSync();
  target.querySelector('button')!.click();
  await settle();
  expect(rowClicks).not.toHaveBeenCalled();
  expect(calls).toEqual(['/sessions/adopted%3Ax%20y/subagents']);
  const dialog = document.getElementById(SUBAGENT_LIST_ID)!.querySelector('[role="dialog"]')!;
  expect(dialog.getAttribute('aria-label')).toBe('subagents of api work');
  const statuses = [...dialog.querySelectorAll('tbody tr')].map((tr) => tr.getAttribute('data-subagent-status'));
  expect(statuses).toEqual(['running', 'unknown', 'done']);
  expect(dialog.textContent).toContain('1 running · 1 done · 1 unknown');
  expect(dialog.textContent).toContain('unknown type');
});

test('not applicable and unreadable are said in words, never as an empty table', async () => {
  const anchor = document.createElement('button');
  document.body.append(anchor);
  for (const [state, words] of [
    ['not_applicable', 'this agent writes no subagent files'],
    ['unchecked', 'the subagent files could not be read'],
  ] as const) {
    reply = payload({ state, counts: null, subagents: [] });
    openSubagentList(anchor, 's', 'n');
    await settle();
    const host = document.getElementById(SUBAGENT_LIST_ID)!;
    expect(host.querySelector(`[data-subagents-empty="${state}"]`)?.textContent).toBe(words);
    expect(host.querySelector('table')).toBeNull();
    expect(host.textContent).not.toContain('0 running');
    closeSubagentList();
  }
  reply = payload({ counts: { total: 0, listed: 0, running: 0, done: 0, unknown: 0, shape_unrecognized: 0, internal: 0 }, subagents: [] });
  openSubagentList(anchor, 's', 'n');
  await settle();
  expect(document.getElementById(SUBAGENT_LIST_ID)!.textContent).toContain('this conversation has launched no subagents');
});

test('a failed read says why, and Escape closes the list', async () => {
  fail = true;
  const anchor = document.createElement('button');
  document.body.append(anchor);
  openSubagentList(anchor, 's', 'n');
  await settle();
  const host = document.getElementById(SUBAGENT_LIST_ID)!;
  expect(host.textContent).toContain('could not read subagents: server said no');
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  flushSync();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

test('pure helpers: counts, totals once per session, empty states, order', () => {
  expect(runningCount(2.7)).toBe(2);
  expect(runningCount(null)).toBeNull();
  expect(runningTotal([
    { session: { id: 'a' }, subagents_running: 2 },
    { session: { id: 'a' }, subagents_running: 2 },
    { session: { id: 'b' }, subagents_running: null },
    { session: { id: 'c' }, subagents_running: 1 },
  ])).toBe(3);
  expect(emptyMessage(payload())).toBeNull();
  expect(orderRows(payload().subagents).map((r) => r.id)).toEqual(['a2', 'a3', 'a1']);
});

test('measuredRunningTotal: ok rows summed, unmeasured rows ignored, all-unmeasured is null (#889)', () => {
  expect(measuredRunningTotal([
    { session: { id: 'a' }, subagents_state: 'ok', subagents_running: 2 },
    { session: { id: 'a' }, subagents_state: 'ok', subagents_running: 2 },
    { session: { id: 'b' }, subagents_state: 'ok', subagents_running: 0 },
    { session: { id: 'c' }, subagents_state: 'ok', subagents_running: 1 },
  ])).toBe(3);

  expect(measuredRunningTotal([
    { session: { id: 'a' }, subagents_state: 'not_applicable', subagents_running: null },
    { session: { id: 'b' }, subagents_state: 'unchecked', subagents_running: null },
  ])).toBeNull();

  expect(measuredRunningTotal([
    { session: { id: 'a' }, subagents_state: 'not_applicable', subagents_running: null },
    { session: { id: 'b' }, subagents_state: 'ok', subagents_running: 4 },
  ])).toBe(4);

  expect(measuredRunningTotal([])).toBeNull();
});

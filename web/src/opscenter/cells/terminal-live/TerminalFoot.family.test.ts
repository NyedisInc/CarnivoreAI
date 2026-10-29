/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { footKindFor } from './foot-family';

const state = vi.hoisted(() => ({ rows: [] as unknown[], usageCalls: 0 }));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessions: { get data() { return state.rows; } },
    sessionUsage: vi.fn(() => { state.usageCalls += 1; return { data: null, status: 'ok' }; }),
    releaseSessionUsage: vi.fn(),
    paneFacts: vi.fn(() => ({ data: null, status: 'ok' })),
    releasePaneFacts: vi.fn(),
  };
});

import TerminalFoot from './TerminalFoot.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const app of mounted.splice(0)) await unmount(app);
  document.body.replaceChildren();
  state.rows = [];
  state.usageCalls = 0;
});

function draw(family: string | null): HTMLElement {
  state.rows = [{ session: { id: 'ses_1' }, agent_family: family, tmux_session: 'cloude_x' }];
  const target = document.createElement('div');
  document.body.appendChild(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width: 1200 } }));
  flushSync();
  return target;
}

test('the decision keys on the recorded family', () => {
  expect(footKindFor('claude')).toBe('stats');
  expect(footKindFor('codex')).toBe('stats');
  expect(footKindFor('shell')).toBe('shell');
  expect(footKindFor('hermes')).toBe('none');
  expect(footKindFor('openclaw')).toBe('none');
  expect(footKindFor('local')).toBe('none');
  expect(footKindFor(null)).toBe('stats');
  expect(footKindFor('unknown')).toBe('stats');
});

test('claude and an unknown family draw the stats bar and poll usage', () => {
  for (const family of ['claude', null, 'unknown']) {
    const root = draw(family);
    expect(root.querySelector('.oc-tf-slot'), `${family} keeps the bar`).not.toBeNull();
    expect(state.usageCalls).toBeGreaterThan(0);
    state.usageCalls = 0;
    mounted.splice(0).forEach((a) => unmount(a));
    document.body.replaceChildren();
  }
});

test('a family with no stats source draws nothing and never polls', () => {
  const root = draw('hermes');
  expect(root.querySelector('.oc-tf-slot')).toBeNull();
  expect(root.querySelector('[data-shell-foot]')).toBeNull();
  expect(state.usageCalls).toBe(0);
});

test('a plain shell keeps its own folder bar, not the stats bar', () => {
  const root = draw('shell');
  expect(root.querySelector('[data-shell-foot]')).not.toBeNull();
  expect(root.querySelector('.oc-tf-slot')).toBeNull();
});

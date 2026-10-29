/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { SessionPaneFacts } from '../../api/types';

const state = vi.hoisted(() => ({
  rows: [] as unknown[],
  facts: null as SessionPaneFacts | null,
  usageCalls: 0,
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessions: { get data() { return state.rows; } },
    sessionUsage: vi.fn(() => { state.usageCalls += 1; return { data: null, status: 'ok' }; }),
    releaseSessionUsage: vi.fn(),
    paneFacts: vi.fn(() => ({ data: state.facts, status: 'ok' })),
    releasePaneFacts: vi.fn(),
  };
});

import TerminalFoot from './TerminalFoot.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const app of mounted.splice(0)) await unmount(app);
  document.body.replaceChildren();
  state.rows = [];
  state.facts = null;
  state.usageCalls = 0;
});

function draw(family: string, width: number): HTMLElement {
  state.rows = [{ session: { id: 'ses_1' }, agent_family: family, tmux_session: 'cloude_x' }];
  const target = document.createElement('div');
  document.body.appendChild(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width } }));
  flushSync();
  return target;
}

const FACTS: SessionPaneFacts = {
  cwd: '/Users/a/src/app',
  cwd_display: '~/src/app',
  command: 'vim',
  git_branch: 'master',
  cols: 177,
  rows: 60,
};

test('a shell draws its folder, program and size, and no usage bar', () => {
  state.facts = FACTS;
  const root = draw('shell', 1200);
  const bar = root.querySelector('[data-shell-foot]');
  expect(bar).not.toBeNull();
  expect(bar!.querySelector('[data-field="cwd"]')?.textContent?.trim()).toBe('~/src/app');
  expect(bar!.querySelector('[data-field="cwd"]')?.hasAttribute('title')).toBe(false);
  expect(bar!.querySelector('[data-field="command"]')?.textContent).toContain('vim');
  expect(bar!.querySelector('[data-field="size"]')?.textContent).toContain('177x60');
  expect(root.querySelector('.oc-tf-slot'), 'the agent usage bar is not drawn').toBeNull();
  expect(state.usageCalls, 'a shell never starts the usage poll').toBe(0);
});

test('narrow: the folder stays, size and program give way', () => {
  state.facts = FACTS;
  const root = draw('shell', 240);
  expect(root.querySelector('[data-field="cwd"]')).not.toBeNull();
  expect(root.querySelector('[data-field="command"]')).toBeNull();
  expect(root.querySelector('[data-field="size"]')).toBeNull();
});

test('an unreadable value is left out, never faked', () => {
  state.facts = { ...FACTS, cols: null, rows: null };
  const root = draw('shell', 1200);
  expect(root.querySelector('[data-field="size"]')).toBeNull();
  expect(root.querySelector('[data-field="cwd"]')).not.toBeNull();
});

test('an agent session keeps the agent usage bar', () => {
  state.facts = FACTS;
  const root = draw('claude', 1200);
  expect(root.querySelector('[data-shell-foot]')).toBeNull();
  expect(root.querySelector('.oc-tf-slot')).not.toBeNull();
  expect(state.usageCalls).toBe(1);
});

test('no repo or branch in either terminal bar: the file browser shows it', () => {
  state.facts = FACTS;
  for (const family of ['shell', 'claude']) {
    const root = draw(family, 1200);
    expect(root.querySelector('[data-git-chip]'), `${family}: no repo chip`).toBeNull();
    expect(root.querySelector('[data-field="branch"]'), `${family}: no branch field`).toBeNull();
    expect(root.textContent, `${family}: the branch name is nowhere on the bar`).not.toContain('master');
  }
});

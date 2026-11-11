/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const wake = vi.hoisted(() => vi.fn(() => Promise.resolve(null)));
vi.mock('../api/asleep.svelte', () => ({
  asleep: { data: [{ id: 7, asleep: true, tmux_name: 'cloude_zz', session_uuid: 'u-7', title: 'zz' }] },
  wakeOrPick: wake,
}));
vi.mock('../api', () => ({
  sessions: { data: [{ tmux_session: 'cloude_live', session: { id: 'ses_live' }, session_row_id: 3 }] },
}));
import { registerDropHost } from '../../lib/motion-grid';
import { beginDrawerTabDrag, commitTabDrop } from './tab-drag';
import { takeWake } from './tabs-motion/carry';
import { terminalLayout } from './layout.svelte';
import { PRIMARY_SLOT } from './model';
import { activeTabFor, resetTabCache, tabsFor } from './tab-groups.svelte';

/** The tabs the page's drop host was asked to carry. */
const carried: string[] = [];
let off: () => void = () => {};

const start = (name: string) => ({ name, pointerId: 1, pointerType: 'mouse', clientX: 10, clientY: 10 });

beforeEach(() => {
  resetTabCache();
  carried.length = 0;
  off = registerDropHost(document.body, {
    id: 'terminal',
    accept: (kind) => {
      carried.push(kind.slice('tab:'.length));
      return true;
    },
  });
  wake.mockClear();
  document.body.innerHTML = '<div id="terminal-grid"><div data-tab-group="' + PRIMARY_SLOT + '"></div></div>';
  const strip = document.querySelector('[data-tab-group]') as HTMLElement;
  strip.getBoundingClientRect = () => ({ left: 0, right: 500, top: 0, bottom: 40, width: 500, height: 40 }) as DOMRect;
});
afterEach(() => {
  off();
  document.body.innerHTML = '';
});

/** The page's side of the hand-off: the carried tab let go over the strip lands through the one commit, then its wake runs. */
const drop = () => {
  const tab = carried[0]!;
  if (commitTabDrop(tab, { kind: 'strip', slot: PRIMARY_SLOT, index: 0 })) takeWake(tab)?.();
};

const PAGE_ID = '0123456789abcdef';

test('a browser-kind row starts a tab drag and the drop lands it as a page tab in that strip', () => {
  expect(beginDrawerTabDrag(start(`browser:${PAGE_ID}`))).toBe(true);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).not.toContain(`page:${PAGE_ID}`);
  drop();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toContain(`page:${PAGE_ID}`);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(`page:${PAGE_ID}`);
  expect(wake).not.toHaveBeenCalled();
});

test('a malformed browser row name starts no drag', () => {
  expect(beginDrawerTabDrag(start('browser:not-an-id'))).toBe(false);
  expect(carried.length).toBe(0);
});

test('a saved Layout takes a page drag too', () => {
  const was = terminalLayout.session;
  terminalLayout.bindKey('layout:5f0c0000-0000-0000-0000-000000000000', terminalLayout.snapshot());
  try {
    expect(beginDrawerTabDrag(start(`browser:${PAGE_ID}`))).toBe(true);
  } finally {
    terminalLayout.bindKey(was, terminalLayout.snapshot());
  }
});

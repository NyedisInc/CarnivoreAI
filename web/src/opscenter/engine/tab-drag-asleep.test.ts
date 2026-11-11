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
import { resetTabCache, tabsFor } from './tab-groups.svelte';

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

test('an asleep row starts a tab drag, and the landing wakes it exactly once', () => {
  expect(beginDrawerTabDrag(start('cloude_zz'))).toBe(true);
  expect(wake).not.toHaveBeenCalled();
  drop();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toContain('terminal:row:7');
  expect(wake).toHaveBeenCalledTimes(1);
  expect(wake).toHaveBeenCalledWith('u-7', 'cloude_zz', 'zz');
});

test('a live row drags as before and wakes nothing', () => {
  expect(beginDrawerTabDrag(start('cloude_live'))).toBe(true);
  drop();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toContain('terminal:row:3');
  expect(wake).not.toHaveBeenCalled();
});

test('a row nobody knows starts no drag', () => {
  expect(beginDrawerTabDrag(start('cloude_nope'))).toBe(false);
});

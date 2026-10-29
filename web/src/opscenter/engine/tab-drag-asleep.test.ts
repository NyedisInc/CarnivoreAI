/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const wake = vi.hoisted(() => vi.fn(() => Promise.resolve(null)));
const gestures = vi.hoisted(() => ({ list: [] as Array<{ onLift: (l: { clientX: number; clientY: number }) => void; onDrop: (a: number, b: number, up: { clientX: number; clientY: number }) => void }> }));
vi.mock('../api/asleep.svelte', () => ({
  asleep: { data: [{ id: 7, asleep: true, tmux_name: 'cloude_zz', session_uuid: 'u-7', title: 'zz' }] },
  wakeOrPick: wake,
}));
vi.mock('../api', () => ({
  sessions: { data: [{ tmux_session: 'cloude_live', session: { id: 'ses_live' }, session_row_id: 3 }] },
}));
vi.mock('./pointer', async (orig) => ({
  ...(await orig<typeof import('./pointer')>()),
  beginGesture: (_el: HTMLElement, _ev: PointerEvent, h: (typeof gestures.list)[number]) => {
    gestures.list.push(h);
    return true;
  },
}));
import { beginDrawerTabDrag } from './tab-drag';
import { terminalLayout } from './layout.svelte';
import { PRIMARY_SLOT } from './model';
import { resetTabCache, tabsFor } from './tab-groups.svelte';

const start = (name: string) => ({ name, pointerId: 1, pointerType: 'mouse', clientX: 10, clientY: 10 });

beforeEach(() => {
  resetTabCache();
  gestures.list.length = 0;
  wake.mockClear();
  document.body.innerHTML = '<div id="terminal-grid"><div data-tab-group="' + PRIMARY_SLOT + '"></div></div>';
  const strip = document.querySelector('[data-tab-group]') as HTMLElement;
  strip.getBoundingClientRect = () => ({ left: 0, right: 500, top: 0, bottom: 40, width: 500, height: 40 }) as DOMRect;
});
afterEach(() => {
  document.body.innerHTML = '';
});

const drop = () => {
  const up = { clientX: 250, clientY: 20 };
  gestures.list[0]!.onLift(up);
  gestures.list[0]!.onDrop(0, 0, up);
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

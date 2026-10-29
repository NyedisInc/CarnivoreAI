/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../opscenter/api', () => ({
  isDemo: () => false,
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import TopBar from '../opscenter/shell/TopBar.svelte';
import {
  POPOUT_DEFAULT,
  POPOUT_GEOMETRY_KEY,
  POPOUT_MIN,
  POPOUT_PATH,
  POPOUT_WINDOW_NAME,
  featuresFor,
  focusMainWindow,
  hasMainWindow,
  openHomePopout,
  parseGeometry,
  rememberGeometry,
} from './popout';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

function setOpener(value: unknown): void {
  Object.defineProperty(window, 'opener', { value, configurable: true, writable: true });
}

function render(popout: boolean): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TopBar, { target, props: { popout } }));
  flushSync();
  return target;
}

test('parseGeometry: a saved size round-trips and a bad one falls back', () => {
  expect(parseGeometry('{"width":800,"height":600,"left":10,"top":20}')).toEqual({ width: 800, height: 600, left: 10, top: 20 });
  expect(parseGeometry(null)).toEqual(POPOUT_DEFAULT);
  expect(parseGeometry('{not json')).toEqual(POPOUT_DEFAULT);
  expect(parseGeometry('{"width":"x","height":5}')).toEqual(POPOUT_DEFAULT);
  expect(parseGeometry('{"width":1,"height":1}')).toEqual({ width: POPOUT_MIN.width, height: POPOUT_MIN.height });
});

test('featuresFor lists the size and, when known, the place', () => {
  expect(featuresFor({ width: 800, height: 600 })).toBe('popup=yes,width=800,height=600');
  expect(featuresFor({ width: 800, height: 600, left: 5, top: 6 })).toBe('popup=yes,width=800,height=600,left=5,top=6');
});

test('openHomePopout opens the stats page in the named window at the saved size', () => {
  localStorage.setItem(POPOUT_GEOMETRY_KEY, '{"width":900,"height":500}');
  const focus = vi.fn();
  const open = vi.fn().mockReturnValue({ focus });
  const win = { open } as unknown as Window;
  openHomePopout(win);
  expect(open).toHaveBeenCalledWith(POPOUT_PATH, POPOUT_WINDOW_NAME, 'popup=yes,width=900,height=500');
  expect(focus).toHaveBeenCalled();
});

test('openHomePopout survives a refused popup', () => {
  const win = { open: vi.fn().mockReturnValue(null) } as unknown as Window;
  expect(openHomePopout(win)).toBeNull();
});

test('focusMainWindow raises the opener, and says false when there is none', () => {
  const focus = vi.fn();
  expect(focusMainWindow({ opener: { closed: false, focus } } as unknown as Window)).toBe(true);
  expect(focus).toHaveBeenCalled();
  expect(focusMainWindow({ opener: null } as unknown as Window)).toBe(false);
  expect(focusMainWindow({ opener: { closed: true, focus } } as unknown as Window)).toBe(false);
  expect(hasMainWindow({ opener: null } as unknown as Window)).toBe(false);
});

test('rememberGeometry saves after a resize settles, on a timer not a frame', () => {
  vi.useFakeTimers();
  const win = window;
  Object.defineProperty(win, 'outerWidth', { value: 700, configurable: true });
  Object.defineProperty(win, 'outerHeight', { value: 500, configurable: true });
  const stop = rememberGeometry(win, 100);
  win.dispatchEvent(new Event('resize'));
  expect(localStorage.getItem(POPOUT_GEOMETRY_KEY)).toBeNull();
  vi.advanceTimersByTime(150);
  expect(parseGeometry(localStorage.getItem(POPOUT_GEOMETRY_KEY)).width).toBe(700);
  stop();
});

test('the pop-out bar is titled, has no drawer door, and focuses the main window', () => {
  const focus = vi.fn();
  setOpener({ closed: false, focus });
  const bar = render(true);
  expect(bar.querySelector('.oc-topbar-title')?.textContent).toBe('carnivore stats');
  expect(bar.querySelector('.oc-topbar-drawer')).toBeNull();
  const link = bar.querySelector<HTMLButtonElement>('.oc-topbar-popout');
  expect(link?.textContent?.trim()).toBe('focus main window');
  link!.click();
  expect(focus).toHaveBeenCalled();
});

test('NEGATIVE: the pop-out bar offers no focus link when nothing opened it', () => {
  setOpener(null);
  expect(render(true).querySelector('.oc-topbar-popout')).toBeNull();
});

test('the pop-out imports nothing that can open a terminal or vote on a pane size', () => {
  const root = process.cwd();
  for (const file of ['main.ts', 'popout.ts']) {
    const src = fs.readFileSync(path.join(root, 'src/popout', file), 'utf8');
    const imports = src.split('\n').filter((line) => /^\s*import\b/.test(line)).join('\n');
    expect(imports).toMatch(/import/);
    expect(imports).not.toMatch(/terminal|size-master|drawer|sessions\/store/i);
  }
});

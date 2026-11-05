/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { initHomeBootRestore, isHeld, type BootRestoreDeps } from './home-boot-restore';
import { LAST_VIEW_KEY } from '../drawer/last-view';

let listing: () => void = () => {};
let terminalUp: () => void = () => {};
let timeout: () => void = () => {};
let screen: string | null | undefined;
let rowsLoaded: boolean;
let navToken: number;
let shownIsRestored: boolean;
let deps: BootRestoreDeps;
let showHome: ReturnType<typeof vi.fn>;
let restore: ReturnType<typeof vi.fn>;
let hold: ReturnType<typeof vi.fn>;
let release: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.setItem(LAST_VIEW_KEY, JSON.stringify({ kind: 'session', sessionId: 'ses_a', tmuxName: 'carnivore_a' }));
  screen = null;
  rowsLoaded = false;
  navToken = 1;
  shownIsRestored = true;
  showHome = vi.fn();
  restore = vi.fn(() => rowsLoaded);
  hold = vi.fn();
  release = vi.fn();
  deps = {
    screen: () => screen,
    wide: () => true,
    held: () => false,
    nav: () => navToken,
    keep: (token) => token === navToken,
    restore: restore as unknown as () => boolean,
    shownIsRestored: () => shownIsRestored,
    whenTerminalUp: (fn) => {
      terminalUp = fn;
      return () => {};
    },
    showHome: showHome as unknown as () => void,
    whenHomeLeft: () => () => {},
    onListing: (fn) => {
      listing = fn;
      return () => {};
    },
    holdPrimary: hold as unknown as (ids: string[]) => void,
    releasePrimary: release as unknown as () => void,
    later: (fn) => {
      timeout = fn;
      return () => {};
    },
  };
});
afterEach(() => {
  localStorage.clear();
  window.history.replaceState(null, '', '/');
  delete (window as unknown as Record<string, unknown>).DeepLinkTarget;
  delete (window as unknown as Record<string, unknown>).LayoutDeepLinkTarget;
});

it('waits for the first paint and the listing, opens the last session, then puts Home over it', () => {
  initHomeBootRestore(deps);
  expect(restore).not.toHaveBeenCalled();
  screen = 'launchpad';
  listing();
  expect(restore).toHaveBeenCalledTimes(1);
  expect(showHome).not.toHaveBeenCalled();
  rowsLoaded = true;
  listing();
  expect(restore).toHaveBeenCalledTimes(2);
  terminalUp();
  timeout();
  expect(showHome).toHaveBeenCalledOnce();
  listing();
  expect(restore).toHaveBeenCalledTimes(2);
});

it('stands down when the person got there first, on a phone width, or with nothing remembered', () => {
  screen = 'launchpad';
  initHomeBootRestore({ ...deps, held: () => true });
  initHomeBootRestore({ ...deps, wide: () => false });
  localStorage.clear();
  initHomeBootRestore(deps);
  expect(restore).not.toHaveBeenCalled();
});

it('leaves Home full window when the session is gone (the record is forgotten)', () => {
  screen = 'launchpad';
  restore.mockImplementation(() => {
    localStorage.removeItem(LAST_VIEW_KEY);
    return false;
  });
  initHomeBootRestore(deps);
  listing();
  expect(restore).toHaveBeenCalledTimes(1);
  expect(showHome).not.toHaveBeenCalled();
  expect(hold).toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});


it('does not put Home over a terminal when the restore never came up and the waiter expires', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  initHomeBootRestore(deps);
  timeout();
  terminalUp();
  expect(showHome).not.toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});

it('does not put Home over a session the person opened themselves during the restore', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  initHomeBootRestore(deps);
  shownIsRestored = false;
  terminalUp();
  expect(showHome).not.toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});

it('does not put Home over a terminal after another navigation superseded the restore', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  initHomeBootRestore(deps);
  const later: Array<() => void> = [];
  deps.later = (fn) => {
    later.push(fn);
    return () => {};
  };
  terminalUp();
  navToken = 2;
  later.forEach((fn) => fn());
  expect(showHome).not.toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});

it('treats a click on the restored session itself during the restore as the person\'s navigation: Home stays off', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  initHomeBootRestore(deps);
  const later: Array<() => void> = [];
  deps.later = (fn) => {
    later.push(fn);
    return () => {};
  };
  navToken = 2;
  terminalUp();
  later.forEach((fn) => fn());
  expect(showHome).not.toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});

it('holds only the restored session: its app id and tmux name', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  initHomeBootRestore(deps);
  expect(hold).toHaveBeenCalledWith(['ses_a', 'carnivore_a']);
});

it('keeps the stop function: stopping releases the hold and drops the waiter', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  const stop = initHomeBootRestore(deps);
  stop();
  terminalUp();
  expect(showHome).not.toHaveBeenCalled();
  expect(release).toHaveBeenCalled();
});


it('is held by a deep link path, a deep link target, a layout target or a menu page', () => {
  expect(isHeld(window, () => false)).toBe(false);
  window.history.replaceState(null, '', '/session/carnivore_b');
  expect(isHeld(window, () => false)).toBe(true);
  window.history.replaceState(null, '', '/');
  (window as unknown as Record<string, unknown>).DeepLinkTarget = 'carnivore_b';
  expect(isHeld(window, () => false)).toBe(true);
  delete (window as unknown as Record<string, unknown>).DeepLinkTarget;
  (window as unknown as Record<string, unknown>).LayoutDeepLinkTarget = 'uuid';
  expect(isHeld(window, () => false)).toBe(true);
  delete (window as unknown as Record<string, unknown>).LayoutDeepLinkTarget;
  expect(isHeld(window, () => true)).toBe(true);
  document.body.classList.add('menu-page-open');
  expect(isHeld(window, () => false)).toBe(true);
  document.body.classList.remove('menu-page-open');
});


it('holds the primary socket closed before the session opens, so it is never marked read', () => {
  screen = 'launchpad';
  rowsLoaded = true;
  const order: string[] = [];
  hold.mockImplementation(() => order.push('hold'));
  restore.mockImplementation(() => {
    order.push('open');
    return true;
  });
  initHomeBootRestore(deps);
  expect(order).toEqual(['hold', 'open']);
  expect(release).not.toHaveBeenCalled();
});

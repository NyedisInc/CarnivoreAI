/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const state = vi.hoisted(() => ({ showing: new Map<string, boolean>() }));

vi.mock('./actions', () => ({
  terminalAction: vi.fn(),
  toolShowing: (slot: string, action: string) => state.showing.get(`${slot}/${action}`) ?? false,
}));
vi.mock('../../api', () => ({
  sessions: { data: [
    { session: { id: 'second' }, tmux_session: 'cloude_second', pinned_theme: 'matrix', agent_type: 'claude' },
  ], refresh: vi.fn() },
  asleep: { refresh: vi.fn() },
  sleepSession: vi.fn(),
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => '' }));

import TerminalActions from './TerminalActions.svelte';
import { terminalAction } from './actions';
import { inputFocus } from '../../lib/input-focus.svelte';

const SLOT = 'terminal:second';
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  state.showing.clear();
});

afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  inputFocus.forget(SLOT);
  inputFocus.forget('terminal:other');
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function setup(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: SLOT, sessionId: 'second', width: 1200 } }));
  flushSync();
  (target.querySelector('.cell-options') as HTMLElement).hidePopover = vi.fn();
  return target;
}

function fakePicker() {
  let onClose: (() => void) | null = null;
  const picker = {
    open: vi.fn((_anchor: HTMLElement, context: { onClose?: () => void }) => {
      picker.close();
      onClose = context.onClose ?? null;
    }),
    close: vi.fn(() => {
      const done = onClose;
      onClose = null;
      done?.();
    }),
  };
  return picker;
}

test('the theme button opens the picker, and a second press closes it', () => {
  const picker = fakePicker();
  vi.stubGlobal('SessionThemeMenu', picker);
  const target = setup();
  const button = target.querySelector('.cell-options [data-tool="theme"]') as HTMLButtonElement;
  expect(button.getAttribute('aria-pressed')).toBe('false');
  button.click();
  flushSync();
  expect(picker.open).toHaveBeenCalledOnce();
  expect(button.getAttribute('aria-pressed')).toBe('true');
  button.click();
  flushSync();
  expect(picker.open).toHaveBeenCalledOnce();
  expect(picker.close).toHaveBeenCalled();
  expect(button.getAttribute('aria-pressed')).toBe('false');
});

test('the picker closing itself (Escape, an outside press) clears the pressed state', () => {
  const picker = fakePicker();
  vi.stubGlobal('SessionThemeMenu', picker);
  const target = setup();
  const button = target.querySelector('.cell-options [data-tool="theme"]') as HTMLButtonElement;
  button.click();
  flushSync();
  picker.close();
  flushSync();
  expect(button.getAttribute('aria-pressed')).toBe('false');
  button.click();
  flushSync();
  expect(picker.open).toHaveBeenCalledTimes(2);
});

test('search draws pressed on the strip and skills in the kebab while showing for this cell', () => {
  const target = setup();
  for (const tool of ['search', 'skills']) {
    state.showing.set(`${SLOT}/${tool}`, true);
  }
  const again = setup();
  expect(again.querySelector('.cell-tools [data-tool="search"]')?.getAttribute('aria-pressed')).toBe('true');
  expect(again.querySelector('.cell-options [data-tool="skills"]')?.getAttribute('aria-pressed')).toBe('true');
  expect(target.querySelector('.cell-tools [data-tool="search"]')?.getAttribute('aria-pressed')).toBe('false');
});

test('the state at pointerdown is what the press acts on, and the press selects this cell', () => {
  const target = setup();
  inputFocus.claim('terminal:other');
  const skills = target.querySelector('.cell-options [data-tool="skills"]') as HTMLButtonElement;
  skills.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  state.showing.set(`${SLOT}/skills`, true);
  skills.click();
  expect(terminalAction).toHaveBeenLastCalledWith(SLOT, 'skills', target.querySelector('[data-tool="overflow"]'), false);
  expect(inputFocus.selected).toBe(SLOT);
  expect(inputFocus.owner).toBe('terminal:other');
  inputFocus.release('terminal:other');
});

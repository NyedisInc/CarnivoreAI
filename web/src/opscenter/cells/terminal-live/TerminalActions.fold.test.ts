/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';
import { splitToolbar, MENU_HOME, STRIP_ITEMS, TOOLBAR_ITEMS } from './toolbar';

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [
    { session: { id: 'second' }, tmux_session: 'cloude_second', pinned_theme: 'matrix', agent_type: 'claude' },
  ], refresh: vi.fn() },
  asleep: { refresh: vi.fn() },
  sleepSession: vi.fn(),
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => '' }));

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  vi.clearAllMocks();
});

const EVERY_ID = TOOLBAR_ITEMS.map((item) => item.id);
const STRIP_IDS = STRIP_ITEMS.map((item) => item.id);
const MENU_IDS = TOOLBAR_ITEMS.filter((item) => MENU_HOME.has(item.id)).map((item) => item.id);

const UTILITIES = createRawSnippet(() => ({ render: () => '<span class="stub-utility"></span>' }));

function render(width: number, slot = 'terminal:@primary'): {
  target: HTMLElement;
  bar(): string[];
  overflow(): string[];
  trigger(): HTMLElement | null;
  crown(): HTMLElement | null;
} {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, {
    target, props: { slot, sessionId: 'second', width, utilities: UTILITIES },
  }));
  flushSync();
  const read = (selector: string): string[] =>
    [...target.querySelectorAll(`${selector} [data-tool]`)]
      .map((el) => el.getAttribute('data-tool') ?? '')
      .filter((id) => id !== 'overflow' && id !== 'actions');
  return {
    target,
    bar: () => read('.cell-tools'),
    overflow: () => read('.cell-options'),
    trigger: () => target.querySelector('[data-tool="overflow"]'),
    crown: () => target.querySelector('.cell-tools [data-tool="size-master"]'),
  };
}

test('the trigger and the kebab menu are drawn at every width, even the widest', () => {
  const view = render(1200);
  expect(view.bar()).toEqual(STRIP_IDS);
  expect(view.overflow()).toEqual(MENU_IDS);
  expect(view.trigger()).not.toBeNull();
  expect(view.crown()?.nextElementSibling).toBe(view.trigger());
});

test('at a middle width the bar holds the most used tools and the overflow holds the rest', () => {
  const view = render(470);
  expect(view.bar()).toEqual(['search', 'sleep', 'size-master']);
  expect(view.overflow()).toEqual([...MENU_IDS, 'utilities']);
  expect(view.trigger()).not.toBeNull();
  expect([...view.bar(), ...view.overflow()].sort()).toEqual([...EVERY_ID].sort());
});

test('at the narrowest the bar is empty and the overflow holds every item', () => {
  const view = render(200);
  expect(view.bar()).toEqual([]);
  expect(view.overflow()).toEqual(EVERY_ID);
  expect(view.trigger()).not.toBeNull();
  expect(view.crown()).toBeNull();
  expect(view.target.querySelector('.cell-options [role="menuitem"][data-tool="size-master"]')).not.toBeNull();
});

test('search survives longest, then sleep, then the crown, then the utilities', () => {
  expect(splitToolbar(250).bar.map((item) => item.id)).toEqual([]);
  expect(splitToolbar(260).bar.map((item) => item.id)).toEqual(['search']);
  expect(splitToolbar(380).bar.map((item) => item.id)).toEqual(['search', 'sleep']);
  expect(splitToolbar(460).bar.map((item) => item.id)).toEqual(['search', 'sleep', 'size-master']);
  expect(splitToolbar(500).bar.map((item) => item.id)).toEqual(STRIP_IDS);
  expect(splitToolbar(500).overflow.map((item) => item.id)).toEqual(MENU_IDS);
  expect(splitToolbar(499).overflow.map((item) => item.id)).toEqual([...MENU_IDS, 'utilities']);
});

test('crossing a threshold back and forth inside the 12px band does not flip the bar', () => {
  const grown = splitToolbar(380, 'notes');
  expect(grown.state).toBe('sleep');
  expect(splitToolbar(370, grown.state).bar.map((item) => item.id)).toEqual(['search', 'sleep']);
  expect(splitToolbar(367, grown.state).bar.map((item) => item.id)).toEqual(['search']);
  let state = grown.state;
  for (const px of [375, 370, 378, 371, 376]) state = splitToolbar(px, state).state;
  expect(state).toBe('sleep');
});

test('a secondary cell keeps its trigger at every width, same as the primary', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, {
    target, props: { slot: 'terminal:second', sessionId: 'second', width: 1200, utilities: UTILITIES },
  }));
  flushSync();
  expect(target.querySelector('[data-tool="overflow"]')).not.toBeNull();
});

test('"make primary" is gone: no item, no text, on the primary or a secondary cell, at any width', () => {
  for (const slot of ['terminal:@primary', 'terminal:second']) {
    for (const width of [200, 470, 1200]) {
      const target = document.createElement('div');
      document.body.append(target);
      mounted.push(mount(TerminalActions, {
        target, props: { slot, sessionId: 'second', width, utilities: UTILITIES },
      }));
      flushSync();
      expect(target.querySelector('[data-tool="make-primary"]')).toBeNull();
      expect(target.querySelector('.oc-tl-action')).toBeNull();
      expect(target.textContent).not.toContain('make primary');
      target.remove();
    }
  }
});

test('the trigger is a real menu button and its menu is a real menu, including the folded background item', () => {
  const view = render(200);
  const trigger = view.trigger() as HTMLElement;
  expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
  expect(trigger.getAttribute('aria-expanded')).toBe('false');
  const menu = view.target.querySelector('.cell-options') as HTMLElement;
  expect(menu.getAttribute('role')).toBe('menu');
  expect(menu.querySelector('[data-tool="theme"]')?.getAttribute('role')).toBe('menuitem');
  expect(menu.querySelector('[data-tool="skills"]')?.getAttribute('role')).toBe('menuitem');
  expect(menu.querySelector('[data-tool="background"] [role="menuitem"]')).not.toBeNull();
});

test('Escape closes the overflow and hands focus back to the trigger', () => {
  const view = render(200);
  const trigger = view.trigger() as HTMLButtonElement;
  const menu = view.target.querySelector('.cell-options') as HTMLElement;
  const hide = vi.fn();
  menu.hidePopover = hide;
  const focus = vi.fn();
  trigger.focus = focus;
  menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(hide).toHaveBeenCalled();
  expect(focus).toHaveBeenCalled();
});

test('ArrowDown and ArrowUp cycle focus through the menu items and wrap', () => {
  const view = render(200);
  const menu = view.target.querySelector('.cell-options') as HTMLElement;
  const items = [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')];
  expect(items.length).toBeGreaterThan(2);
  items[0]?.focus();
  menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  expect(document.activeElement).toBe(items[1]);
  menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
  expect(document.activeElement).toBe(items[0]);
  menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
  expect(document.activeElement).toBe(items[items.length - 1]);
});


/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';
import { terminalAction } from './actions';

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
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function setup(width = 1200): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: 'terminal:second', sessionId: 'second', width } }));
  flushSync();
  (target.querySelector('.cell-options') as HTMLElement).hidePopover = vi.fn();
  return target;
}

test('the palette carries this cell identity from the kebab, where the theme lives', () => {
  const open = vi.fn();
  vi.stubGlobal('SessionThemeMenu', { open });
  const wide = setup(1200);
  (wide.querySelector('.cell-options [data-tool="theme"]') as HTMLButtonElement).click();
  expect(open).toHaveBeenLastCalledWith(wide.querySelector('[data-tool="overflow"]'), expect.objectContaining({ sessionName: 'cloude_second', pinnedTheme: 'matrix' }));
  const narrow = setup(200);
  (narrow.querySelector('.cell-options [data-tool="theme"]') as HTMLButtonElement).click();
  expect(open).toHaveBeenLastCalledWith(narrow.querySelector('[data-tool="overflow"]'), expect.objectContaining({ sessionName: 'cloude_second', pinnedTheme: 'matrix' }));
});

test('files, notes and theme are kebab rows at every width, never strip icons', () => {
  for (const width of [1200, 200]) {
    const view = setup(width);
    for (const id of ['files', 'notes', 'theme']) {
      expect(view.querySelector(`.cell-tools [data-tool="${id}"]`)).toBeNull();
      expect(view.querySelector(`.cell-options [data-tool="${id}"]`)?.getAttribute('role')).toBe('menuitem');
    }
  }
});

test('each folded tool routes through the owning slot and the visible kebab anchor', () => {
  const target = setup(200);
  for (const action of ['skills', 'plugins', 'files', 'search']) {
    (target.querySelector(`.cell-options [data-tool="${action}"]`) as HTMLButtonElement).click();
    expect(terminalAction).toHaveBeenLastCalledWith('terminal:second', action, target.querySelector('[data-tool="overflow"]'), undefined);
  }
});

test('the same tool in the BAR routes through the control the user actually pressed', () => {
  const target = setup(1200);
  const button = target.querySelector('.cell-tools [data-tool="search"]') as HTMLButtonElement;
  button.click();
  expect(terminalAction).toHaveBeenLastCalledWith('terminal:second', 'search', button, undefined);
});

test('overflow opens before shared placement measures it and fits the visual viewport', () => {
  const target = setup(200);
  const menu = target.querySelector('.cell-options') as HTMLElement;
  const toggle = vi.fn(() => true);
  menu.togglePopover = toggle;
  vi.stubGlobal('visualViewport', { height: 180 });
  const place = vi.fn((element: HTMLElement) => {
    expect(toggle).toHaveBeenCalledOnce();
    expect(element.style.maxHeight).toBe('164px');
  });
  vi.stubGlobal('AnchorPopover', { place });
  const anchor = target.querySelector('[data-tool="overflow"]') as HTMLButtonElement;
  anchor.click();
  expect(place).toHaveBeenCalledWith(menu, anchor);
  toggle.mockReturnValue(false);
  anchor.click();
  expect(place).toHaveBeenCalledOnce();
});

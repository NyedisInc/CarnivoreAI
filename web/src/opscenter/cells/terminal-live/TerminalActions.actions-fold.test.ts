/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [
    { session: { id: 'ses_a' }, tmux_session: 'cloude_a', label: 'a', activity_status: 'idle', pinned_theme: 'alien', host_key: 'local' },
  ], refresh: vi.fn() },
  asleep: { refresh: vi.fn() },
  sleepSession: vi.fn(),
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => '' }));

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

function setup(width = 1200) {
  let onClose: (() => void) | undefined;
  const open = vi.fn((_ctx: unknown, _anchor: Element, _at: unknown, opts?: { onClose?: () => void }) => { onClose = opts?.onClose; return true; });
  const close = vi.fn(() => onClose?.());
  vi.stubGlobal('CloudeWeb', { rowMenu: { openRow: open, closeRow: close, isOpen: () => true } });
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: 'terminal:ses_a', sessionId: 'ses_a', width, sessionName: 'cloude_a' } }));
  flushSync();
  const options = target.querySelector('.cell-options') as HTMLElement;
  options.hidePopover = vi.fn();
  const item = target.querySelector('[data-tool="actions"]') as HTMLButtonElement;
  return { open, close, options, item };
}

test('pressing actions folds the row menu out beside the item and leaves the kebab menu open', () => {
  const { open, options, item } = setup();
  item.click();
  flushSync();
  expect(options.hidePopover).not.toHaveBeenCalled();
  expect(open).toHaveBeenCalledOnce();
  expect(open.mock.calls[0]![1]).toBe(item);
  const opts = open.mock.calls[0]![3] as Record<string, unknown>;
  expect(opts).toMatchObject({ nestedIn: options });
  expect(opts.pinnedTheme).toBeUndefined();
  expect(item.getAttribute('aria-expanded')).toBe('true');
});

test('a real mouse: hover opens the fold-out, the FIRST press keeps it open, a second press retracts it', () => {
  const { open, close, item } = setup();
  item.dispatchEvent(new PointerEvent('pointerenter'));
  flushSync();
  item.dispatchEvent(new PointerEvent('pointerenter'));
  expect(open).toHaveBeenCalledOnce();
  item.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  item.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
  item.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  flushSync();
  expect(close).not.toHaveBeenCalled();
  expect(item.getAttribute('aria-expanded')).toBe('true');
  item.click();
  expect(close).toHaveBeenCalledOnce();
  flushSync();
  expect(item.getAttribute('aria-expanded')).toBe('false');
});

test('a press with no hover first (touch, keyboard) opens it, and a second press retracts it', () => {
  const { open, close, item } = setup();
  item.click();
  flushSync();
  expect(open).toHaveBeenCalledOnce();
  item.click();
  expect(close).toHaveBeenCalledOnce();
});

test('hovering a sibling item retracts the fold-out', () => {
  const { close, options, item } = setup(200);
  item.click();
  flushSync();
  const sibling = options.querySelector('[role="menuitem"]:not([data-tool="actions"])') as HTMLElement;
  sibling.dispatchEvent(new PointerEvent('pointerover', { bubbles: true }));
  expect(close).toHaveBeenCalledOnce();
});

test('ArrowRight on the focused actions item opens the fold-out', () => {
  const { open, options, item } = setup();
  item.focus();
  options.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  expect(open).toHaveBeenCalledOnce();
});

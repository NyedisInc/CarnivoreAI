/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';
import { terminalAction } from './actions';
import { terminalLayout } from '../../engine/layout.svelte';
import { layoutZoom, watchZoomKeys } from '../../engine/layout-zoom.svelte';
import type { Layout } from '../../engine/types';

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
let baseline: Layout;

beforeEach(() => {
  baseline = terminalLayout.snapshot();
});

afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  terminalLayout.restore(baseline);
  layoutZoom.restore();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function setup(groupSlot: string | null, width = 1200): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, {
    target,
    props: { slot: 'terminal:second', sessionId: 'second', width, groupSlot },
  }));
  flushSync();
  (target.querySelector('.cell-options') as HTMLElement).hidePopover = vi.fn();
  return target;
}

function searchButton(root: HTMLElement): HTMLButtonElement {
  return root.querySelector('.cell-tools [data-tool="search"]') as HTMLButtonElement;
}

function holdShift(): void {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift', shiftKey: true }));
  flushSync();
}

function releaseShift(): void {
  window.dispatchEvent(new KeyboardEvent('keyup', { key: 'Shift', shiftKey: false }));
  flushSync();
}

test('a layout of one component: Shift held does not swap the icon, and Shift+Click is a plain click', () => {
  expect(layoutZoom.canZoom).toBe(false);
  const root = setup('terminal:second');
  holdShift();
  expect(searchButton(root).querySelector('[data-icon="search"]')).not.toBeNull();
  expect(searchButton(root).classList.contains('tool-zoom-armed')).toBe(false);
  searchButton(root).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  flushSync();
  expect(terminalAction).toHaveBeenCalledWith('terminal:second', 'search', searchButton(root), undefined);
  expect(layoutZoom.zoomed).toBeNull();
});

test('a second component: Shift held swaps the magnifying glass to expand, in a different colour, and back on release', () => {
  terminalLayout.add('terminal', 'ses_a');
  expect(layoutZoom.canZoom).toBe(true);
  const root = setup('terminal:second');
  holdShift();
  expect(searchButton(root).querySelector('[data-icon="expand"]')).not.toBeNull();
  expect(searchButton(root).classList.contains('tool-zoom-armed')).toBe(true);
  releaseShift();
  expect(searchButton(root).querySelector('[data-icon="search"]')).not.toBeNull();
  expect(searchButton(root).classList.contains('tool-zoom-armed')).toBe(false);
});

test('no groupSlot (outside a terminal-page grid): Shift held never swaps the icon', () => {
  terminalLayout.add('terminal', 'ses_a');
  const root = setup(null);
  holdShift();
  expect(searchButton(root).querySelector('[data-icon="search"]')).not.toBeNull();
});

test('Shift+Click zooms the component; a plain click still opens search', () => {
  terminalLayout.add('terminal', 'ses_a');
  const root = setup('terminal:second');
  searchButton(root).dispatchEvent(new MouseEvent('click', { bubbles: true }));
  flushSync();
  expect(terminalAction).toHaveBeenCalledWith('terminal:second', 'search', searchButton(root), undefined);
  expect(layoutZoom.zoomed).toBeNull();

  vi.clearAllMocks();
  searchButton(root).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  flushSync();
  expect(terminalAction).not.toHaveBeenCalled();
  expect(layoutZoom.zoomed).toBe('terminal:second');
});

test('the leave-full-screen icon shows only while zoomed, right of the magnifying glass, and restores on click', () => {
  terminalLayout.add('terminal', 'ses_a');
  const root = setup('terminal:second');
  expect(root.querySelector('[data-tool="leave-fullscreen"]')).toBeNull();

  layoutZoom.toggle('terminal:second');
  flushSync();
  const leave = root.querySelector('[data-tool="leave-fullscreen"]') as HTMLButtonElement;
  expect(leave).not.toBeNull();
  expect(searchButton(root).nextElementSibling).toBe(leave);

  leave.click();
  flushSync();
  expect(layoutZoom.zoomed).toBeNull();
  expect(root.querySelector('[data-tool="leave-fullscreen"]')).toBeNull();
});

test('Shift+Esc restores while zoomed; a plain Esc, and Shift+Esc with nothing zoomed, pass through untouched', () => {
  const stop = watchZoomKeys();
  try {
    terminalLayout.add('terminal', 'ses_a');
    layoutZoom.toggle('terminal:second');

    const plainEsc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    window.dispatchEvent(plainEsc);
    expect(layoutZoom.zoomed).toBe('terminal:second');
    expect(plainEsc.defaultPrevented).toBe(false);

    const shiftEsc = new KeyboardEvent('keydown', { key: 'Escape', shiftKey: true, bubbles: true, cancelable: true });
    window.dispatchEvent(shiftEsc);
    expect(layoutZoom.zoomed).toBeNull();
    expect(shiftEsc.defaultPrevented).toBe(true);

    const idleShiftEsc = new KeyboardEvent('keydown', { key: 'Escape', shiftKey: true, bubbles: true, cancelable: true });
    window.dispatchEvent(idleShiftEsc);
    expect(idleShiftEsc.defaultPrevented).toBe(false);
  } finally {
    stop();
  }
});

test('Cmd+Shift+Enter toggles the zoom on the focused terminal\'s component, exactly as Shift+Click does', () => {
  const stop = watchZoomKeys();
  try {
    const cell = document.createElement('div');
    cell.dataset.slot = 'terminal:@primary';
    const input = document.createElement('textarea');
    cell.append(input);
    document.body.append(cell);
    input.focus();
    const chord = (): KeyboardEvent => {
      const event = new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, shiftKey: true, bubbles: true, cancelable: true });
      input.dispatchEvent(event);
      return event;
    };

    const single = chord();
    expect(layoutZoom.zoomed).toBeNull();
    expect(single.defaultPrevented).toBe(false);

    terminalLayout.add('terminal', 'ses_a');
    const zoomIn = chord();
    expect(layoutZoom.zoomed).toBe('terminal:@primary');
    expect(zoomIn.defaultPrevented).toBe(true);

    const zoomOut = chord();
    expect(layoutZoom.zoomed).toBeNull();
    expect(zoomOut.defaultPrevented).toBe(true);

    const newline = new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true });
    input.dispatchEvent(newline);
    expect(layoutZoom.zoomed).toBeNull();
    expect(newline.defaultPrevented).toBe(false);
  } finally {
    stop();
  }
});

test('zooming never writes into terminalLayout\'s own (synced) layout value', () => {
  terminalLayout.add('terminal', 'ses_a');
  const before = JSON.stringify(terminalLayout.state.layout);
  layoutZoom.toggle('terminal:second');
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
  layoutZoom.toggle('terminal:second');
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
});

test('folded to the overflow menu (a narrow component): Shift+Click still zooms, a plain click still opens search', () => {
  terminalLayout.add('terminal', 'ses_a');
  const root = setup('terminal:second', 200);
  expect(searchButton(root)).toBeNull();
  const overflowSearch = () => root.querySelector('.cell-options [data-tool="search"]') as HTMLButtonElement;
  expect(overflowSearch()).not.toBeNull();

  holdShift();
  expect(overflowSearch().classList.contains('tool-zoom-armed')).toBe(true);
  expect(overflowSearch().querySelector('[data-icon="expand"]')).not.toBeNull();
  releaseShift();

  overflowSearch().dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  flushSync();
  expect(terminalAction).not.toHaveBeenCalled();
  expect(layoutZoom.zoomed).toBe('terminal:second');
  expect(root.querySelector('.cell-options [data-tool="leave-fullscreen"]')).not.toBeNull();

  layoutZoom.restore();
  overflowSearch().dispatchEvent(new MouseEvent('click', { bubbles: true }));
  flushSync();
  expect(terminalAction).toHaveBeenCalledWith('terminal:second', 'search', expect.anything(), undefined);
  expect(layoutZoom.zoomed).toBeNull();
});

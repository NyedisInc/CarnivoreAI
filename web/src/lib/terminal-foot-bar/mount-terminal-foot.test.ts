/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const panel = vi.hoisted(() => ({
  ensured: [] as string[],
  unmounted: [] as string[],
  sessions: [] as string[],
  handle: { setSession: (id: string) => { panel.sessions.push(id); } },
}));

vi.mock('../mount', () => ({
  ensurePanel: (id: string) => {
    panel.ensured.push(id);
    return panel.handle;
  },
  unmountPanel: (id: string) => {
    panel.unmounted.push(id);
    return true;
  },
  panelInstance: () => panel.handle,
}));

const currentSession = vi.hoisted(() => ({ id: '' }));
vi.mock('../../opscenter/api', () => ({
  primarySessionId: () => currentSession.id,
}));

import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import {
  TERMINAL_FOOT_CONTAINER_ID,
  mountTerminalFoot,
  unmountTerminalFoot,
} from './mount-terminal-foot';

/** Say whether this browser reports itself wide enough for the grid. */
function setWide(isWide: boolean): { addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> } {
  const mq = { matches: isWide, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  Object.defineProperty(window, 'matchMedia', {
    configurable: true, writable: true,
    value: () => mq,
  });
  return mq;
}

function buildPage(gridActive = false): HTMLElement {
  document.body.innerHTML = '';
  const grid = document.createElement('div');
  grid.id = 'terminal-grid';
  const container = document.createElement('div');
  container.id = 'terminal-container';
  grid.appendChild(container);
  if (gridActive) {
    const surface = document.createElement('div');
    surface.className = 'oc-surface';
    grid.appendChild(surface);
  }
  document.body.appendChild(grid);
  const bar = document.createElement('div');
  bar.id = TERMINAL_FOOT_CONTAINER_ID;
  document.body.appendChild(bar);
  return bar;
}

beforeEach(() => {
  panel.ensured.length = 0;
  panel.unmounted.length = 0;
  panel.sessions.length = 0;
  currentSession.id = '';
  setWide(true);
  delete (window as unknown as { Themes?: unknown }).Themes;
  delete (window as unknown as { ThemeNavigation?: unknown }).ThemeNavigation;
  delete (window as unknown as { TerminalController?: unknown }).TerminalController;
  delete (window as unknown as { TerminalLayout?: unknown }).TerminalLayout;
});

afterEach(() => {
  unmountTerminalFoot();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

test('a page with no #terminal-foot-bar is a no-op, not a fault', () => {
  document.body.innerHTML = '';
  expect(mountTerminalFoot()).toBe(false);
  expect(panel.ensured).toEqual([]);
});

test('the bar shows the session already bound before this module could hear the event', () => {
  buildPage();
  currentSession.id = 'ses_already_bound';
  expect(mountTerminalFoot()).toBe(true);
  expect(panel.ensured).toEqual([TERMINAL_FOOT_CONTAINER_ID]);
  expect(panel.sessions.at(-1)).toBe('ses_already_bound');
});

test('a session-bind announcement swaps which session the bar shows', () => {
  buildPage();
  mountTerminalFoot();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(panel.sessions.at(-1)).toBe('ses_a');
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_b' } }));
  expect(panel.sessions.at(-1)).toBe('ses_b');
});

test('the dashboard grid taking over blanks the bar rather than showing it twice', () => {
  buildPage(true);
  mountTerminalFoot();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(panel.sessions.at(-1)).toBe('');
});

test('a bare bind announcement with no session id blanks the bar', () => {
  buildPage();
  mountTerminalFoot();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: {} }));
  expect(panel.sessions.at(-1)).toBe('');
});

test('wiring twice installs one listener, not two', () => {
  buildPage();
  mountTerminalFoot();
  mountTerminalFoot();
  panel.sessions.length = 0;
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(panel.sessions).toEqual(['ses_a']);
});

test('the bar is painted with the session\'s own theme pin through the legacy scope path', () => {
  buildPage();
  const applyScopeTo = vi.fn(() => vi.fn());
  const resolvePinnedTheme = vi.fn(() => 'alien');
  (window as unknown as { Themes: unknown }).Themes = { applyScopeTo };
  (window as unknown as { ThemeNavigation: unknown }).ThemeNavigation = { resolvePinnedTheme };
  (window as unknown as { TerminalController: unknown }).TerminalController = { _currentSession: { id: 'ses_a' } };

  mountTerminalFoot();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));

  expect(resolvePinnedTheme).toHaveBeenCalledWith({ id: 'ses_a' });
  expect(applyScopeTo).toHaveBeenCalledWith(
    document.getElementById(TERMINAL_FOOT_CONTAINER_ID),
    { pinnedTheme: 'alien' },
  );
});

test('a session switch releases the previous theme scope before painting the next', () => {
  buildPage();
  const releaseA = vi.fn();
  const releaseB = vi.fn();
  let calls = 0;
  const applyScopeTo = vi.fn(() => (calls++ === 0 ? releaseA : releaseB));
  (window as unknown as { Themes: unknown }).Themes = { applyScopeTo };

  mountTerminalFoot();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(releaseA).not.toHaveBeenCalled();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_b' } }));
  expect(releaseA).toHaveBeenCalledTimes(1);
});

test('every apply asks the fit pipeline to re-measure the pane', () => {
  buildPage();
  const requestFit = vi.fn();
  (window as unknown as { TerminalLayout: unknown }).TerminalLayout = { requestFit };

  mountTerminalFoot();
  expect(requestFit).toHaveBeenCalledWith(TERMINAL_FOOT_CONTAINER_ID);
  requestFit.mockClear();
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(requestFit).toHaveBeenCalledWith(TERMINAL_FOOT_CONTAINER_ID);
});

test('crossing the grid\'s own width re-checks which session the bar should show', async () => {
  buildPage();
  currentSession.id = 'ses_a';
  const mq = setWide(true);
  mountTerminalFoot();
  expect(panel.sessions.at(-1)).toBe('ses_a');

  const surface = document.createElement('div');
  surface.className = 'oc-surface';
  document.getElementById('terminal-grid')?.appendChild(surface);
  const onChange = mq.addEventListener.mock.calls.find(([name]) => name === 'change')?.[1] as
    (() => void) | undefined;
  expect(onChange).toBeTypeOf('function');
  onChange?.();
  await new Promise((resolve) => { setTimeout(resolve, 80); });
  expect(panel.sessions.at(-1)).toBe('');
});

test('unmounting undoes every listener and takes the panel down', () => {
  buildPage();
  mountTerminalFoot();
  unmountTerminalFoot();
  expect(panel.unmounted).toContain(TERMINAL_FOOT_CONTAINER_ID);
  panel.sessions.length = 0;
  window.dispatchEvent(new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }));
  expect(panel.sessions).toEqual([]);
});

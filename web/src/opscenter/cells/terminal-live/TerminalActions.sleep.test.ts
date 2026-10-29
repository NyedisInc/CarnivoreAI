/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';

const state = vi.hoisted(() => ({ primary: '' }));
const mocks = vi.hoisted(() => ({
  sleepSession: vi.fn(),
  refreshSessions: vi.fn(),
  refreshAsleep: vi.fn(),
}));
const { sleepSession, refreshSessions, refreshAsleep } = mocks;

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [
    { session: { id: 'second' }, tmux_session: 'cloude_second', pinned_theme: 'matrix', agent_type: 'claude' },
    { session: { id: 'no-uuid' }, tmux_session: 'cloude_third', pinned_theme: 'matrix', agent_type: 'claude' },
  ], refresh: mocks.refreshSessions },
  asleep: { refresh: mocks.refreshAsleep },
  sleepSession: mocks.sleepSession,
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => state.primary }));

function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  state.primary = '';
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function stubIdentityBridge(map: Record<string, string>): void {
  vi.stubGlobal('SessionSidebarGroupMembership', {
    uuidOfName: (name: string) => map[name] ?? null,
  });
}

function setup(sessionId: string, width = 1200): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: `terminal:${sessionId}`, sessionId, width } }));
  flushSync();
  (target.querySelector('.cell-options') as HTMLElement).hidePopover = vi.fn();
  return target;
}

test('the sleep button is eligible for a row the sidebar identity bridge has matched to a uuid', () => {
  stubIdentityBridge({ cloude_second: 'u-second' });
  const target = setup('second');
  const button = target.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement;
  expect(button).not.toBeNull();
  expect(button.disabled).toBe(false);
  expect(button.getAttribute('aria-label')).toBe('sleep this session');
});

test('the sleep button is disabled for a row this browser has not matched to a stored session', () => {
  stubIdentityBridge({});
  const target = setup('no-uuid');
  const button = target.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement;
  expect(button.disabled).toBe(true);
});

test('the sleep button is disabled while the sidebar identity bridge has not loaded at all', () => {
  const target = setup('second');
  const button = target.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement;
  expect(button.disabled).toBe(true);
});

test('a click calls the same sleepSession route, then refreshes both lists', async () => {
  stubIdentityBridge({ cloude_second: 'u-second' });
  sleepSession.mockResolvedValue({ status: 'asleep', session_uuid: 'u-second' });
  const target = setup('second');
  const button = target.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement;
  button.click();
  await settle();
  expect(sleepSession).toHaveBeenCalledWith('u-second');
  expect(refreshSessions).toHaveBeenCalledWith(true);
  expect(refreshAsleep).toHaveBeenCalled();
});

test('a refusal leaves both lists untouched', async () => {
  stubIdentityBridge({ cloude_second: 'u-second' });
  sleepSession.mockResolvedValue({ status: 'refused', detail: 'restart in flight' });
  const target = setup('second');
  const button = target.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement;
  button.click();
  await settle();
  expect(refreshSessions).not.toHaveBeenCalled();
  expect(refreshAsleep).not.toHaveBeenCalled();
});

test('sleeping the page\'s own primary pane dispatches the hand-off event; a secondary cell never does', async () => {
  stubIdentityBridge({ cloude_second: 'u-second' });
  sleepSession.mockResolvedValue({ status: 'asleep', session_uuid: 'u-second' });
  const heard = vi.fn();
  window.addEventListener('cloude:primary-session-gone', heard);
  try {
    const secondary = setup('second');
    (secondary.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement).click();
    await settle();
    expect(heard).not.toHaveBeenCalled();

    state.primary = 'second';
    const primary = setup('second');
    (primary.querySelector('.cell-tools [data-tool="sleep"]') as HTMLButtonElement).click();
    await settle();
    expect(heard).toHaveBeenCalledOnce();
    expect((heard.mock.calls[0]![0] as CustomEvent).detail).toEqual({ sessionId: 'second' });
  } finally {
    window.removeEventListener('cloude:primary-session-gone', heard);
  }
});

test('the sleep item also renders, and works, from the folded kebab presentation', async () => {
  stubIdentityBridge({ cloude_second: 'u-second' });
  sleepSession.mockResolvedValue({ status: 'asleep', session_uuid: 'u-second' });
  const target = setup('second', 200);
  expect(target.querySelector('.cell-tools [data-tool="sleep"]')).toBeNull();
  const overflow = target.querySelector('.cell-options [data-tool="sleep"]') as HTMLButtonElement;
  expect(overflow).not.toBeNull();
  expect(overflow.textContent?.trim()).toBe('sleep this session');
  overflow.click();
  await settle();
  expect(sleepSession).toHaveBeenCalledWith('u-second');
});

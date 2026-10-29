/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalActions from './TerminalActions.svelte';
import { t } from '../../../lib/i18n/index.svelte';

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [
    { session: { id: 'ses_a' }, tmux_session: 'cloude_a', label: 'a', activity_status: 'idle', created_by_us: true, host_key: 'local' },
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

function setup(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: 'terminal:ses_a', sessionId: 'ses_a', width: 1200, sessionName: 'cloude_a' } }));
  flushSync();
  (target.querySelector('.cell-options') as HTMLElement).hidePopover = vi.fn();
  return target;
}

test('background reads "background" and actions is the last menu item', () => {
  const items = [...setup().querySelectorAll('.cell-options > *')];
  expect(t('terminal.background.open')).toBe('background');
  expect(items.at(-1)?.getAttribute('data-tool')).toBe('actions');
  expect(items.at(-1)?.textContent).toContain('actions');
  expect(setup().textContent).not.toContain('terminal background');
});

test('actions hands this session to the row menu opener with the row menu context', () => {
  const openRow = vi.fn(() => true);
  vi.stubGlobal('CloudeWeb', { rowMenu: { openRow, isOpen: () => false, closeRow: () => {} } });
  vi.stubGlobal('SessionSidebarGroupMembership', { uuidOfName: () => 'u-a' });
  const target = setup();
  (target.querySelector('[data-tool="actions"]') as HTMLButtonElement).click();
  expect(openRow).toHaveBeenCalledOnce();
  const ctx = (openRow.mock.calls[0] as unknown[])[0] as Record<string, unknown>;
  expect(ctx).toMatchObject({ name: 'cloude_a', sessionId: 'ses_a', sessionUuid: 'u-a', status: 'idle', owned: true });
});

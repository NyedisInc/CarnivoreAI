/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TerminalActions from './TerminalActions.svelte';

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [{ session: { id: 'sh1' }, tmux_session: 'carnivore_console-1', agent_family: 'shell' }], refresh: vi.fn() },
  asleep: { refresh: vi.fn() },
  sleepSession: vi.fn(),
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => '' }));

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
});

function draw(width: number, agentFamily: string | null): { kebab: Element | null; menu: string[] } {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, {
    target, props: { slot: 'terminal:row:9', sessionId: 'sh1', width, sessionName: 'carnivore_console-1', agentFamily },
  }));
  flushSync();
  return {
    kebab: target.querySelector('.cell-tools [data-tool="overflow"]'),
    menu: [...target.querySelectorAll('.cell-options [data-tool]')].map((el) => el.getAttribute('data-tool') ?? ''),
  };
}

test('a shell kebab lists files, notes, theme, background and actions, and no agent-only drawer', () => {
  const { kebab, menu } = draw(1000, 'shell');
  expect(kebab).not.toBeNull();
  expect(menu).toEqual(['files', 'notes', 'theme', 'background', 'actions']);
});

test('a narrow shell strip folds its icons into the same kebab, never into nothing', () => {
  const { kebab, menu } = draw(0, 'shell');
  expect(kebab).not.toBeNull();
  for (const id of ['files', 'notes', 'theme', 'background', 'search', 'sleep', 'size-master', 'actions']) {
    expect(menu, id).toContain(id);
  }
  expect(menu).not.toContain('skills');
  expect(menu).not.toContain('plugins');
});

test('a claude session keeps its skills and plugins drawers in the kebab', () => {
  const { menu } = draw(1000, 'claude');
  expect(menu.slice(0, 2)).toEqual(['skills', 'plugins']);
});

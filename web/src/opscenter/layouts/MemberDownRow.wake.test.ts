/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const api = vi.hoisted(() => ({
  asleep: { data: [{ id: 7, asleep: true, title: 'api', tmux_name: 'carnivore_api' }], refresh: vi.fn() },
  recent: { data: null as unknown, refresh: vi.fn() },
  sessions: { data: [] as unknown[], status: 'ok', refresh: vi.fn() },
  wakeOrPick: vi.fn(),
}));
vi.mock('../api', () => api);

import MemberDownRow from './MemberDownRow.svelte';

let instance: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (instance) unmount(instance);
  instance = null;
  document.body.replaceChildren();
});

test('a rejected refresh after the wake leaves the button usable', async () => {
  api.wakeOrPick.mockResolvedValue({ status: 'started', detail: '' });
  api.asleep.refresh.mockRejectedValue(new Error('listing down'));
  api.sessions.refresh.mockResolvedValue(undefined);
  const host = document.createElement('div');
  document.body.append(host);
  instance = mount(MemberDownRow, { target: host, props: { member: { session_row_id: 7, session_uuid: 'u7', position: 0 } as never } });
  flushSync();
  const button = document.querySelector<HTMLButtonElement>('[data-member-action="wake"]')!;
  button.click();
  await vi.waitFor(() => expect(api.asleep.refresh).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
  expect(button.disabled).toBe(false);
});

async function pressWake(): Promise<void> {
  api.asleep.refresh.mockResolvedValue(undefined);
  api.sessions.refresh.mockResolvedValue(undefined);
  const host = document.createElement('div');
  document.body.append(host);
  instance = mount(MemberDownRow, { target: host, props: { member: { session_row_id: 7, session_uuid: 'u7', position: 0 } as never } });
  flushSync();
  document.querySelector<HTMLButtonElement>('[data-member-action="wake"]')!.click();
  await vi.waitFor(() => expect(api.sessions.refresh).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
}

test.each([
  ['restart_in_progress', 'a restart of this session is already running.'],
  ['session_not_asleep', 'this session is not asleep, so there is nothing to wake.'],
])('a wake that rejects with %s shows the server sentence', async (_code, sentence) => {
  api.wakeOrPick.mockRejectedValue(new Error(sentence));
  await pressWake();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(sentence);
});

test('a wake that answers started shows no error', async () => {
  api.wakeOrPick.mockResolvedValue({ status: 'started', detail: '' });
  await pressWake();
  expect(document.querySelector('[role="alert"]')).toBeNull();
});

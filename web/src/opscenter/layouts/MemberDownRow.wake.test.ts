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

/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ calls: [] as { path: string; body: string }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle/send') return { results: [{ list: '12', status: 'sent', target: 'ses_1' }] };
      return {};
    },
  };
});

import TaskManagerScheduleOffer from './TaskManagerScheduleOffer.svelte';
import { cplugEnablement } from '../host/enablement.svelte';
import type { HuddleItem, TaskManagerMessage } from './huddle-model';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

const item = { id: 7, list: '12' } as unknown as HuddleItem;
const WHEN = '2099-10-20T09:00:00-04:00';
const message = (state: 'offered' | 'accepted' | null): TaskManagerMessage => ({
  id: 31, item_id: 7, author: 'claude', kind: 'info', text: 'keeping them a week', answered: false, created_at: 0, seq: 3,
  ...(state ? { schedule: { when: WHEN, title: 'delete the moved files', state } } : {}),
}) as TaskManagerMessage;

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { flushSync(); await tick(); await new Promise((r) => setTimeout(r, 0)); }
}

function draw(msg: TaskManagerMessage): HTMLElement {
  const host = document.createElement('div');
  document.body.append(host);
  app = mount(TaskManagerScheduleOffer, { target: host, props: { item, message: msg } });
  flushSync();
  return host;
}

beforeEach(() => { server.calls = []; });
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

describe('the schedule offer key', () => {
  test('an offer draws one key with the date; a press accepts then tells the list at once', async () => {
    const host = draw(message('offered'));
    const key = host.querySelector<HTMLButtonElement>('[data-task-manager-schedule-offer="31"]')!;
    expect(key.dataset.state).toBe('offered');
    expect(key.disabled).toBe(false);
    expect(key.textContent).toMatch(/oct 20/);
    key.click();
    await settle();
    const paths = server.calls.map((c) => c.path);
    expect(paths[0]).toBe('/cplugs/huddle/items/7/messages/31/schedule');
    expect(paths.indexOf('/cplugs/huddle/send'), 'the tell follows the accept').toBeGreaterThan(0);
    expect(JSON.parse(server.calls[paths.indexOf('/cplugs/huddle/send')]!.body)).toEqual({ lists: ['12'], targets: {} });
  });

  test('an accepted offer is a quiet mark that cannot be pressed', async () => {
    const host = draw(message('accepted'));
    const key = host.querySelector<HTMLButtonElement>('[data-task-manager-schedule-offer="31"]')!;
    expect(key.dataset.state).toBe('accepted');
    expect(key.disabled).toBe(true);
    expect(key.textContent).toContain('scheduled');
    key.click();
    await settle();
    expect(server.calls).toEqual([]);
  });

  test('a message with no offer draws nothing', () => {
    expect(draw(message(null)).querySelector('[data-task-manager-schedule-offer]')).toBeNull();
  });
});

/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const server = vi.hoisted(() => ({ up: false, posts: [] as { path: string; body: Record<string, unknown> }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'POST') {
        if (!server.up && /\/inbox$/.test(path)) throw Object.assign(new Error('down'), { status: 0 });
        server.posts.push({ path, body: JSON.parse(String(init.body ?? '{}')) });
        return /\/inbox$/.test(path) ? { queued: true, entry: null, item: null, duplicate: false } : { results: [] };
      }
      return {};
    },
  };
});

import { addItem, huddle } from './huddle.svelte';
import { entries, retryNow, stopOutbox } from '../../lib/outbox/outbox';
import { resetStore } from '../../lib/outbox/outbox-store';

beforeEach(() => {
  server.up = false;
  server.posts = [];
  huddle.addTarget = '12';
  globalThis.localStorage?.clear();
  resetStore();
});
afterEach(() => stopOutbox());

describe('the add box through the outbox', () => {
  test('an add the server did not answer is kept with its text, then sent again under the same id and tells its list once', async () => {
    expect(await addItem('fix the login\nand the logout')).toBe('kept');
    expect(huddle.notice).toContain('saved in this browser');
    const [kept] = entries();
    expect(kept).toMatchObject({ kind: 'add', state: 'pending', attempts: 1 });
    expect(kept?.label.text).toBe('fix the login\nand the logout');
    server.up = true;
    const out = await retryNow(kept!.id);
    expect(out.ok).toBe(true);
    const inbox = server.posts.filter((p) => p.path.endsWith('/inbox'));
    expect(inbox).toHaveLength(1);
    expect(inbox[0]?.body).toMatchObject({ text: 'fix the login\nand the logout', client_id: kept!.id });
    expect(inbox[0]?.body.retry_age_s).toBeTypeOf('number');
    expect(server.posts.filter((p) => p.path === '/cplugs/huddle/send')).toHaveLength(1);
    expect(entries()).toHaveLength(0);
  });
});

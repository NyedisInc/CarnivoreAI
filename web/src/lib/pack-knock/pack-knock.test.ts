/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

const calls: Array<{ path: string; method: string; body: string }> = [];
let listing: Array<Record<string, unknown>> = [];
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  auth: { state: 'signed-in', notice: '' },
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, method: init?.method ?? 'GET', body: String(init?.body ?? '') });
    if (init?.method === 'DELETE') {
      listing = listing.filter((k) => !path.endsWith(`/${k.id}`));
      return { deleted: true };
    }
    return { knocks: listing };
  },
}));

const knock = (id: string, extra: Record<string, unknown> = {}) => ({
  id, label: "Alex's MacBook", addr: '10.0.0.7', fid_short: 'ab12cd', code: '482915',
  expires_at: new Date(Date.now() + 600_000).toISOString(), attempts_left: 3, ...extra,
});
const q = (sel: string) => document.querySelector(sel) as HTMLElement | null;
const settle = async () => {
  await vi.advanceTimersByTimeAsync(0);
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};

beforeEach(() => {
  vi.useFakeTimers();
  calls.length = 0;
  listing = [];
  document.body.innerHTML = '';
  vi.resetModules();
});
afterEach(() => vi.useRealTimers());

it('shows the code, hides until a new knock, not me deletes, an empty re-read closes', async () => {
  const { setLocale } = await import('../i18n/index.svelte');
  setLocale('en');
  const { resourcePush } = await import('../resource-push/boot');
  const push = resourcePush().store;
  push.hello({ resource_topics: ['pack_knocks'] });
  listing = [knock('inv-1')];
  const { bootPackKnock } = await import('./boot');
  bootPackKnock();
  await settle();

  expect(q('[data-pack-knock="popup"]')).not.toBeNull();
  expect(q('[data-pack-knock="who"]')!.textContent).toContain("Alex's MacBook");
  expect(q('[data-pack-knock="who"]')!.textContent).toContain('10.0.0.7');
  expect(q('[data-pack-knock="code"]')!.textContent!.replace(/\s/g, '')).toBe('482915');
  expect(document.activeElement).toBe(q('[data-pack-knock="hide"]'));

  q('[data-pack-knock="hide"]')!.click();
  await settle();
  expect(q('[data-pack-knock="popup"]')).toBeNull();

  listing = [knock('inv-2', { code: '111222' })];
  push.frame({ topics: ['pack_knocks'] });
  await settle();
  expect(q('[data-pack-knock="code"]')!.textContent!.replace(/\s/g, '')).toBe('111222');

  q('[data-pack-knock="not-me"]')!.click();
  await settle();
  expect(calls.some((c) => c.method === 'DELETE' && c.path === '/computers/knocks/inv-2')).toBe(true);
  expect(q('[data-pack-knock="popup"]')).toBeNull();

  listing = [knock('inv-3')];
  push.frame({ topics: ['pack_knocks'] });
  await settle();
  expect(q('[data-pack-knock="popup"]')).not.toBeNull();
  listing = [];
  push.frame({ topics: ['pack_knocks'] });
  await settle();
  expect(q('[data-pack-knock="popup"]')).toBeNull();

  expect(calls.every((c) => c.body === '' && !c.path.includes('482915') && !c.path.includes('111222'))).toBe(true);
});

/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

vi.mock('../lib/mount', () => ({ mountPanel: () => null }));
vi.mock('../opscenter/App.svelte', () => ({ default: {} }));
vi.mock('./SingleWidget.svelte', () => ({ default: {} }));
vi.mock('./TabPopout.svelte', () => ({ default: {} }));
vi.mock('../opscenter/engine/home-sync.svelte', () => ({ startHomeSync: () => {} }));

type Frame = { type?: string };
const page = globalThis as unknown as Record<string, unknown>;

afterEach(() => {
  delete page.AppEvents;
  delete page.API;
  delete page.ListingPush;
});

test('the pop-out entry boots the listing push and resyncs on the events hello', async () => {
  const handlers: Array<(f: Frame) => void> = [];
  page.AppEvents = {
    subscribe: (h: (f: Frame) => void) => { handlers.push(h); return () => {}; },
    isConnected: () => false,
  };
  const call = vi.fn(async () => ({ stream: 's1', seq: 1, collections: { list: { rows: [] } } }));
  page.API = { call };

  await import('./main');

  const push = page.ListingPush as { isLive(): boolean } | undefined;
  expect(push).toBeDefined();
  expect(push!.isLive()).toBe(false);

  for (const h of handlers) h({ type: 'events.hello' });
  await vi.waitFor(() => expect(push!.isLive()).toBe(true));
  expect(call).toHaveBeenCalledWith('/sessions/listing');
});

/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

const mounted: string[] = [];
vi.mock('../lib/mount', () => ({ mountPanel: (id: string) => { mounted.push(id); return null; } }));
vi.mock('../opscenter/App.svelte', () => ({ default: {} }));
vi.mock('./SingleWidget.svelte', () => ({ default: {} }));
vi.mock('./TabPopout.svelte', () => ({ default: {} }));
vi.mock('../opscenter/engine/home-sync.svelte', () => ({ startHomeSync: () => {} }));
const server = vi.hoisted(() => ({ build: 'aaa' }));
vi.mock('../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<typeof import('../opscenter/api/auth.svelte')>()),
  authFetch: vi.fn(async (path: string) => (path === '/version' ? { version: '1.0.0', client_build: server.build } : {})),
}));

type Frame = { type?: string; [k: string]: unknown };
const page = globalThis as unknown as Record<string, unknown>;

afterEach(() => {
  delete page.AppEvents;
  delete page.API;
  delete page.ListingPush;
  delete page.ResourcePush;
});

test('the pop-out boots every push channel, resyncs on reconnect, and flags a newer build and a drop', async () => {
  const handlers: Array<(f: Frame) => void> = [];
  let connected = false;
  page.AppEvents = {
    subscribe: (h: (f: Frame) => void) => { handlers.push(h); return () => {}; },
    isConnected: () => connected,
    lastHello: () => null,
  };
  const send = (f: Frame): void => { for (const h of [...handlers]) h(f); };
  const call = vi.fn(async () => ({ stream: 's1', seq: 1, collections: { list: { rows: [] } } }));
  page.API = { call };

  await import('./main');
  const { startEvents } = await import('../opscenter/api/events.svelte');
  startEvents();
  const { versionWatch, bannerKind } = await import('../lib/version-watch/version-watch.svelte');
  const { connection } = await import('../lib/live-status/connection.svelte');

  const listing = page.ListingPush as { isLive(): boolean } | undefined;
  const resources = page.ResourcePush as { isLive(t: string): boolean; pushOrPoll(r: () => void, ms: number, t: string[]): () => void } | undefined;
  expect(listing).toBeDefined();
  expect(resources).toBeDefined();
  expect(mounted).toEqual(expect.arrayContaining(['version-banner-container', 'popout-offline-marker']));
  await vi.waitFor(() => expect(versionWatch.pageClientBuild).toBe('aaa'));

  const taskManagerRead = vi.fn();
  resources!.pushOrPoll(taskManagerRead, 60_000, ['huddle:all']);

  connected = true;
  send({ type: 'events.open' });
  send({ type: 'events.hello', resource_topics: ['huddle', 'client_build'], server_version: '1.0.0', client_build: 'aaa' });
  await vi.waitFor(() => expect(listing!.isLive()).toBe(true));
  expect(resources!.isLive('huddle:all')).toBe(true);
  expect(taskManagerRead).toHaveBeenCalledTimes(1);
  expect(connection.live).toBe(true);
  expect(bannerKind(versionWatch)).toBeNull();

  send({ type: 'resources.changed', topics: ['huddle:all'], seq: 1 });
  expect(taskManagerRead).toHaveBeenCalledTimes(2);

  connected = false;
  send({ type: 'events.closed', code: 1006 });
  expect(connection.live).toBe(false);
  expect(listing!.isLive()).toBe(false);
  expect(resources!.isLive('huddle:all')).toBe(false);

  server.build = 'bbb';
  connected = true;
  const random = vi.spyOn(Math, 'random').mockReturnValue(0);
  send({ type: 'events.open' });
  send({ type: 'events.hello', resource_topics: ['huddle', 'client_build'], server_version: '1.0.0', client_build: 'bbb' });
  await vi.waitFor(() => expect(listing!.isLive()).toBe(true));
  expect(call).toHaveBeenCalledTimes(2);
  expect(taskManagerRead).toHaveBeenCalledTimes(3);
  expect(connection.live).toBe(true);
  expect(bannerKind(versionWatch)).toBe('client');
  random.mockRestore();
});

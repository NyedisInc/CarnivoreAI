/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import {
  OFFLINE_GRACE_MS,
  _resetConnectionForTest,
  ageParts,
  connection,
  offlineAge,
  startConnectionWatch,
  type ConnectionHost,
} from './connection.svelte';
import OfflineMarker from './OfflineMarker.svelte';

type Frame = { type?: string };

function fakeHost(): ConnectionHost & { send(f: Frame): void; reconnectNow: ReturnType<typeof vi.fn<(manual?: boolean) => void>> } {
  const handlers: Array<(f: Frame) => void> = [];
  return {
    subscribe: (h) => { handlers.push(h); return () => {}; },
    isConnected: () => false,
    reconnectNow: vi.fn<(manual?: boolean) => void>(),
    send: (f) => { for (const h of handlers) h(f); },
  };
}

describe('the offline marker', () => {
  let shown: Record<string, unknown> | null = null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    _resetConnectionForTest();
  });

  afterEach(() => {
    if (shown) unmount(shown);
    shown = null;
    document.body.innerHTML = '';
    vi.useRealTimers();
  });

  test('offlineAge is null while live and inside the grace, the age after it', () => {
    expect(offlineAge({ live: true, everLive: true, downSince: 0 }, 99_999)).toBeNull();
    expect(offlineAge({ live: false, everLive: true, downSince: 0 }, OFFLINE_GRACE_MS - 1)).toBeNull();
    expect(offlineAge({ live: false, everLive: true, downSince: 0 }, 60_000)).toBe(60_000);
    expect(ageParts(150_000)).toEqual({ unit: 'minutes', count: 2 });
    expect(ageParts(7_200_000)).toEqual({ unit: 'hours', count: 2 });
  });

  test('hidden while live, shown with the age once the drop outlasts the grace, retry reconnects', () => {
    const host = fakeHost();
    startConnectionWatch(host, () => Date.now());
    const target = document.createElement('div');
    document.body.append(target);
    shown = mount(OfflineMarker, { target });

    host.send({ type: 'events.open' });
    flushSync();
    expect(connection.live).toBe(true);
    expect(target.querySelector('[data-offline-marker]')).toBeNull();

    vi.setSystemTime(10_000);
    host.send({ type: 'events.closed' });
    expect(connection.downSince).toBe(10_000);
    vi.advanceTimersByTime(OFFLINE_GRACE_MS - 1000);
    flushSync();
    expect(target.querySelector('[data-offline-marker]')).toBeNull();

    vi.advanceTimersByTime(120_000);
    flushSync();
    const marker = target.querySelector('[data-offline-marker]');
    expect(marker).not.toBeNull();
    expect(marker!.textContent).toContain('offline, data may be stale');
    expect(marker!.textContent).toContain('last live 2m ago');

    (marker!.querySelector('button') as HTMLButtonElement).click();
    expect(host.reconnectNow).toHaveBeenCalledWith(true);

    host.send({ type: 'events.hello' });
    flushSync();
    expect(target.querySelector('[data-offline-marker]')).toBeNull();
  });
});

describe('the events client wake probe (client/js/app-events.js)', () => {
  class FakeSocket {
    readyState = 0;
    sent: string[] = [];
    closedWith: number | null = null;
    onopen: (() => void) | null = null;
    onmessage: ((e: { data: string }) => void) | null = null;
    onclose: ((e: { code: number }) => void) | null = null;
    onerror: (() => void) | null = null;
    send(data: string): void { this.sent.push(data); }
    close(code: number): void { this.closedWith = code; }
  }
  const sockets: FakeSocket[] = [];
  type Events = {
    start(): void; stop(): void; subscribe(h: (f: Frame) => void): () => void;
    reconnectNow(manual?: boolean): void; isConnected(): boolean; PROBE_TIMEOUT_MS: number;
  };
  let events: Events;

  beforeEach(async () => {
    vi.useFakeTimers();
    sockets.length = 0;
    const g = globalThis as unknown as Record<string, unknown>;
    g.API = {
      getToken: () => 'tok',
      openWebSocket: () => { const s = new FakeSocket(); sockets.push(s); return s; },
    };
    vi.resetModules();
    await import('../../../../client/js/app-events.js');
    events = g.AppEvents as Events;
  });

  afterEach(() => {
    events.stop();
    vi.useRealTimers();
  });

  function open(): FakeSocket {
    events.start();
    const s = sockets[sockets.length - 1]!;
    s.readyState = 1;
    s.onopen!();
    return s;
  }

  test('an unanswered probe drops the socket as closed and reconnects', () => {
    const frames: string[] = [];
    events.subscribe((f) => frames.push(String(f.type)));
    const s = open();
    events.reconnectNow();
    expect(s.sent).toEqual([JSON.stringify({ type: 'ping' })]);
    vi.advanceTimersByTime(events.PROBE_TIMEOUT_MS + 1);
    expect(frames).toContain('events.closed');
    expect(s.closedWith).toBe(4000);
    expect(events.isConnected()).toBe(false);
    vi.advanceTimersByTime(2000);
    expect(sockets.length).toBe(2);
  });

  test('a probe answered by any frame leaves the socket alone', () => {
    const s = open();
    events.reconnectNow();
    s.onmessage!({ data: JSON.stringify({ type: 'pong' }) });
    vi.advanceTimersByTime(events.PROBE_TIMEOUT_MS + 1);
    expect(s.closedWith).toBeNull();
    expect(events.isConnected()).toBe(true);
    expect(sockets.length).toBe(1);
  });

  test('a channel down on a backoff step reconnects at once; a stopped one only when asked', () => {
    const s = open();
    s.readyState = 3;
    s.onclose!({ code: 1006 });
    expect(sockets.length).toBe(1);
    events.reconnectNow();
    expect(sockets.length).toBe(2);
    events.stop();
    events.reconnectNow();
    expect(sockets.length).toBe(2);
    events.reconnectNow(true);
    expect(sockets.length).toBe(3);
  });
});

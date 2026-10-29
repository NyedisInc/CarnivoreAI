import { afterEach, describe, expect, it, vi } from 'vitest';

const ACCESS_KEY = 'claude_tunnel_token';
const REFRESH_KEY = 'claude_refresh_token';

function fakeStorage(seed: Record<string, string>) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
}

function fakeHost() {
  const handlers: Array<(frame: unknown) => void> = [];
  return {
    client: {
      subscribe(handler: (frame: unknown) => void): () => void {
        handlers.push(handler);
        return () => void handlers.splice(handlers.indexOf(handler), 1);
      },
      isConnected: (): boolean => true,
    },
    deliver(frame: unknown): void {
      for (const handler of [...handlers]) handler(frame);
    },
  };
}

let asked: string[] = [];

async function load() {
  (globalThis as { localStorage?: unknown }).localStorage = fakeStorage({
    [ACCESS_KEY]: 'an-access-token',
    [REFRESH_KEY]: 'a-refresh-token',
  });
  asked = [];
  (globalThis as { fetch?: unknown }).fetch = vi.fn(async (url: string) => {
    asked.push(String(url));
    return {
      ok: true,
      status: 200,
      json: async () => [],
    } as unknown as Response;
  });
  const host = fakeHost();
  (globalThis as { AppEvents?: unknown }).AppEvents = host.client;

  vi.resetModules();
  const poll = await import('./poll.svelte');
  const sessions = await import('./sessions.svelte');
  const events = await import('./events.svelte');
  return { poll, sessions, events, host };
}

function listReads(): number {
  return asked.filter((url) => url.includes('/sessions/list')).length;
}

async function readsReach(target: number): Promise<void> {
  for (let waited = 0; waited < 2000; waited += 10) {
    if (listReads() >= target) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`/sessions/list was read ${listReads()} times, wanted ${target}`);
}

describe('a rename re-reads the listing even while the poll is paused', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as { localStorage?: unknown }).localStorage;
    delete (globalThis as { AppEvents?: unknown }).AppEvents;
    delete (globalThis as { fetch?: unknown }).fetch;
  });

  it('reads the listing again when a session.renamed frame arrives', async () => {
    const { poll, events, host } = await load();
    events.startEvents();
    await readsReach(1);

    poll.pauseAll();
    const before = listReads();

    host.deliver({ type: 'session.renamed', session_id: 'ses_a', new_name: 'triage' });
    await readsReach(before + 1);

    expect(listReads()).toBe(before + 1);
  });

  it('reads nothing extra for a frame that is not a rename', async () => {
    const { poll, events, host } = await load();
    events.startEvents();
    await readsReach(1);

    poll.pauseAll();
    const before = listReads();

    host.deliver({ type: 'session.status', session_id: 'ses_a', activity_status: 'working' });
    host.deliver({ type: 'session.renamed', session_id: 'ses_a', new_name: 'triage' });
    await readsReach(before + 1);

    expect(listReads()).toBe(before + 1);
  });
});

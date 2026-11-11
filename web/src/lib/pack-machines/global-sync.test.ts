import { beforeEach, describe, expect, it, vi } from 'vitest';

const calls: Array<{ path: string; init?: { method?: string; body?: string } }> = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    calls.push({ path, init });
    return { settings: { enabled: false, auto: false, claude: true, codex: true }, is_main: true, computers: [] };
  },
}));

beforeEach(() => {
  calls.length = 0;
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
});

describe('gateWord', () => {
  it('a blocking gate wins over the last pass, a known one has its own word, an unknown one a generic word', async () => {
    const { gateWord } = await import('./global-sync-store.svelte');
    expect(gateWord({ gate: 'not_approved', last: { state: 'synced' } })).toBe('pack.globalsync.gate.not_approved');
    expect(gateWord({ gate: 'something_new', last: null })).toBe('pack.globalsync.gate.other');
    expect(gateWord({ gate: null, last: { state: 'synced' } })).toBe('pack.globalsync.last.synced');
    expect(gateWord({ gate: null, last: null })).toBe('pack.globalsync.last.none');
  });
});

describe('the writes', () => {
  it('saves a partial settings body with PUT and sync now posts the chosen computers', async () => {
    const { saveGlobalSync, syncNow } = await import('./global-sync-store.svelte');
    await saveGlobalSync({ enabled: true });
    await syncNow(['iid-b']);
    const put = calls.find((c) => c.init?.method === 'PUT');
    const post = calls.find((c) => c.init?.method === 'POST');
    expect(put?.path).toBe('/pack/global-sync');
    expect(JSON.parse(put?.init?.body ?? '{}')).toEqual({ enabled: true });
    expect(post?.path).toBe('/pack/global-sync/sync');
    expect(JSON.parse(post?.init?.body ?? '{}')).toEqual({ install_ids: ['iid-b'] });
  });
});

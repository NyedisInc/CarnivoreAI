import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const calls: Array<{ path: string; method: string; body: unknown }> = [];
let answers: unknown[] = [];
let refreshCalls = 0;

vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetch: (path: string, init: RequestInit = {}) => {
    calls.push({
      path,
      method: (init.method ?? 'GET').toUpperCase(),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
    });
    const next = answers.shift();
    if (next instanceof Error) return Promise.reject(next);
    return Promise.resolve(next);
  },
}));

vi.mock('../../opscenter/api/poll.svelte', () => ({
  resource: () => ({
    data: [],
    refresh: async () => { refreshCalls += 1; },
  }),
}));

type EventHandler = (frame: unknown) => void;
let capturedHandler: EventHandler | null = null;
vi.mock('../../opscenter/api/events.svelte', () => ({
  subscribe: (_type: string, handler: EventHandler) => {
    capturedHandler = handler;
    return () => { capturedHandler = null; };
  },
}));

class FakeApiError extends Error {
  code: string;
  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

type Mod = typeof import('./api.svelte');

async function load(): Promise<Mod> {
  vi.resetModules();
  calls.length = 0;
  answers = [];
  refreshCalls = 0;
  return import('./api.svelte');
}

describe('the Layouts bridge writes', () => {
  beforeEach(() => {
    delete (globalThis as Record<string, unknown>).SessionSidebar;
  });
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).SessionSidebar;
  });

  it('renames through PATCH, re-reads the list, and repaints the drawer', async () => {
    const mod = await load();
    const layout = { layout_uuid: 'L1', name: 'api + web' };
    answers = [layout];
    const repaint = vi.fn(async () => {});
    (globalThis as Record<string, unknown>).SessionSidebar = { _fetchAndRender: repaint, _lastSig: 'x' };
    const out = await mod.renameLayout('L1', 'api + web + db');
    expect(calls).toEqual([
      { path: '/layouts/L1', method: 'PATCH', body: { name: 'api + web + db' } },
    ]);
    expect(out).toEqual(layout);
    expect(refreshCalls).toBe(1);
    expect(repaint).toHaveBeenCalledTimes(1);
  });

  it('deletes through DELETE without touching member sessions', async () => {
    const mod = await load();
    answers = [undefined];
    await mod.deleteLayout('L1');
    expect(calls).toEqual([{ path: '/layouts/L1', method: 'DELETE', body: null }]);
    expect(refreshCalls).toBe(1);
  });

  it('reorders with the whole desired order, never a delta', async () => {
    const mod = await load();
    answers = [{ status: 'ok', layouts: [], detail: null }];
    await mod.reorderLayouts(['L2', 'L1']);
    expect(calls).toEqual([
      { path: '/layouts/order', method: 'PUT', body: { layout_uuids: ['L2', 'L1'] } },
    ]);
  });

  it('sets style through PUT, re-reads the list, and repaints the drawer', async () => {
    const mod = await load();
    const layout = { layout_uuid: 'L1', colour: 'teal', gradient: 'tide', animation: 'shimmer' };
    answers = [layout];
    const repaint = vi.fn(async () => {});
    (globalThis as Record<string, unknown>).SessionSidebar = { _fetchAndRender: repaint, _lastSig: 'x' };
    const out = await mod.setLayoutStyle('L1', { colour: 'teal', gradient: 'tide', animation: 'shimmer' });
    expect(calls).toEqual([
      { path: '/layouts/L1/style', method: 'PUT', body: { colour: 'teal', gradient: 'tide', animation: 'shimmer' } },
    ]);
    expect(out).toEqual(layout);
    expect(refreshCalls).toBe(1);
    expect(repaint).toHaveBeenCalledTimes(1);
  });

  it('an invalid style propagates the server code untouched', async () => {
    const mod = await load();
    answers = [new FakeApiError('colour must be one of cyan, violet, ...', 'layout_style_invalid')];
    await expect(mod.setLayoutStyle('L1', { colour: 'nope', gradient: null, animation: 'none' }))
      .rejects.toMatchObject({ code: 'layout_style_invalid' });
  });

  it('a refused write propagates the server code untouched', async () => {
    const mod = await load();
    answers = [new FakeApiError("a layout called 'x' already exists", 'layout_name_taken')];
    await expect(mod.renameLayout('L1', 'x')).rejects.toMatchObject({ code: 'layout_name_taken' });
  });

  it('a missing drawer costs the repaint, never the write', async () => {
    const mod = await load();
    answers = [{ layout_uuid: 'L1', name: 'renamed' }];
    await expect(mod.renameLayout('L1', 'renamed')).resolves.toBeTruthy();
  });

  it('a remote sessions.changed(layouts) frame re-reads AND repaints (issue #821)', async () => {
    const mod = await load();
    mod.wireLayoutsRefresh();
    const repaint = vi.fn(async () => {});
    (globalThis as Record<string, unknown>).SessionSidebar = { _fetchAndRender: repaint, _lastSig: 'x' };
    capturedHandler?.({ reason: 'layouts' });
    await Promise.resolve();
    await Promise.resolve();
    expect(refreshCalls).toBeGreaterThan(0);
    expect(repaint).toHaveBeenCalled();
  });

  it('a frame with a different reason neither re-reads nor repaints', async () => {
    const mod = await load();
    mod.wireLayoutsRefresh();
    const repaint = vi.fn(async () => {});
    (globalThis as Record<string, unknown>).SessionSidebar = { _fetchAndRender: repaint, _lastSig: 'x' };
    capturedHandler?.({ reason: 'groups' });
    await Promise.resolve();
    expect(refreshCalls).toBe(0);
    expect(repaint).not.toHaveBeenCalled();
  });
});

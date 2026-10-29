import { describe, expect, it, vi } from 'vitest';
import { createSnapshotStore, HOT_MS, WALL_MS, wallIntervalMs, type Snapshot, type StoreDeps } from './snapshot-store';

function rig(answers: (ids: string[]) => Record<string, Snapshot>) {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
  const calls: Array<Array<{ id: string; hash?: string }>> = [];
  let visible = true;
  let onVis = () => {};
  const deps: StoreDeps = {
    fetchScreens: async (items) => {
      calls.push(items);
      return answers(items.map((i) => i.id));
    },
    now: () => Date.now(),
    setTimer: (cb, ms) => setTimeout(cb, ms),
    clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    pageVisible: () => visible,
    onVisibility: (cb) => { onVis = cb; return () => {}; },
  };
  return { store: createSnapshotStore(deps), calls, hide: () => { visible = false; onVis(); }, show: () => { visible = true; onVis(); } };
}

const shot = (hash: string): Snapshot => ({ status: 'ok', cols: 80, rows: 24, hash, screen: hash });

describe('snapshot store', () => {
  it('wallIntervalMs is 125 ms per tile clamped to 1 s..5 s', () => {
    for (const [n, ms] of [[1, 1000], [8, 1000], [16, 2000], [40, 5000], [100, 5000]] as const) expect(wallIntervalMs(n)).toBe(ms);
  });

  it('reads every subscribed tile in ONE request, every 1 s while the wall is small, the hovered tile every 1 s', async () => {
    const r = rig((ids) => Object.fromEntries(ids.map((id) => [id, shot('h1')])));
    for (const id of ['a', 'b', 'c']) r.store.subscribe(id, () => {});
    await vi.advanceTimersByTimeAsync(1);
    expect(r.calls.length).toBe(1);
    expect(r.calls[0]!.map((i) => i.id)).toEqual(['a', 'b', 'c']);
    await vi.advanceTimersByTimeAsync(HOT_MS * 3);
    expect(r.calls.length).toBe(4);
    r.store.setHot('b');
    await vi.advanceTimersByTimeAsync(1);
    const before = r.calls.length;
    await vi.advanceTimersByTimeAsync(HOT_MS * 3);
    expect(r.calls.length - before).toBeGreaterThanOrEqual(3);
    expect(r.calls.slice(before).every((c) => c.some((i) => i.id === 'b' && i.hash === 'h1'))).toBe(true);
  });

  it('hovering many tiles in a row never stacks polling chains: one timer, one chain', async () => {
    const r = rig((ids) => Object.fromEntries(ids.map((id) => [id, shot('h1')])));
    const ids = Array.from({ length: 20 }, (_, i) => `t${i}`);
    for (const id of ids) r.store.subscribe(id, () => {});
    await vi.advanceTimersByTimeAsync(1);
    for (const id of ids) {
      r.store.setHot(id);
      await vi.advanceTimersByTimeAsync(1);
    }
    r.store.releaseHot(ids[ids.length - 1]!);
    expect(vi.getTimerCount()).toBe(1);
    const before = r.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(vi.getTimerCount()).toBe(1);
    expect(r.calls.length - before).toBeLessThanOrEqual(5);
  });

  it('with 40 subscribed tiles the wall reads every 5 s and only the hovered tile every 1 s', async () => {
    const r = rig((ids) => Object.fromEntries(ids.map((id) => [id, shot('h1')])));
    for (let i = 0; i < 40; i++) r.store.subscribe(`t${i}`, () => {});
    await vi.advanceTimersByTimeAsync(1);
    expect(r.calls.length).toBe(1);
    r.store.setHot('t3');
    await vi.advanceTimersByTimeAsync(1);
    const before = r.calls.length;
    await vi.advanceTimersByTimeAsync(HOT_MS * 3);
    expect(r.calls.slice(before).every((c) => c.length === 1 && c[0]!.id === 't3')).toBe(true);
    expect(r.calls.length - before).toBeGreaterThanOrEqual(3);
    await vi.advanceTimersByTimeAsync(WALL_MS);
    expect(r.calls.some((c) => c.length === 40)).toBe(true);
  });

  it('an answer that omits a tile (unchanged hash) calls nobody; pausing and no subscribers stop the timer', async () => {
    const r = rig(() => ({}));
    const got = vi.fn();
    const off = r.store.subscribe('a', got);
    await vi.advanceTimersByTimeAsync(1);
    expect(got).not.toHaveBeenCalled();
    r.hide();
    const n = r.calls.length;
    await vi.advanceTimersByTimeAsync(WALL_MS * 3);
    expect(r.calls.length).toBe(n);
    r.show();
    await vi.advanceTimersByTimeAsync(1);
    expect(r.calls.length).toBe(n + 1);
    off();
    await vi.advanceTimersByTimeAsync(WALL_MS * 3);
    expect(r.calls.length).toBe(n + 1);
  });

  it('unreachable keeps the held hash (the next tick can skip an unchanged screen); older clears it', async () => {
    let status: Snapshot['status'] = 'ok';
    const r = rig((ids) => Object.fromEntries(ids.map((id) => [id, status === 'ok' ? shot('h1') : { ...shot(''), status }])));
    r.store.subscribe('a', () => {});
    await vi.advanceTimersByTimeAsync(1);
    status = 'unreachable';
    await vi.advanceTimersByTimeAsync(HOT_MS);
    status = 'older';
    await vi.advanceTimersByTimeAsync(HOT_MS);
    await vi.advanceTimersByTimeAsync(HOT_MS);
    expect(r.calls.map((c) => c[0]!.hash)).toEqual([undefined, 'h1', 'h1', undefined]);
  });

  it('a paired computer that never answers never stalls the local tiles: one remote request, one timer', async () => {
    const r = rig((ids) => (ids.some((id) => id.startsWith('remote:'))
      ? (new Promise(() => {}) as unknown as Record<string, Snapshot>)
      : Object.fromEntries(ids.map((id) => [id, shot('h1')]))));
    for (const id of ['a', 'remote:p:b']) r.store.subscribe(id, () => {});
    await vi.advanceTimersByTimeAsync(1);
    await vi.advanceTimersByTimeAsync(5 * HOT_MS);
    const local = r.calls.filter((c) => c.every((i) => !i.id.startsWith('remote:')));
    const remote = r.calls.filter((c) => c.some((i) => i.id.startsWith('remote:')));
    expect(local.length).toBeGreaterThanOrEqual(5);
    expect(remote.length).toBe(1);
    expect(vi.getTimerCount()).toBeLessThanOrEqual(1);
  });
});

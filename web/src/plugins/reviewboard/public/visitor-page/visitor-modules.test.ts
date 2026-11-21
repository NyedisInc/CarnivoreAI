import { describe, expect, it, vi } from 'vitest';
import { createAutosave, DEBOUNCE_MS, LIMITED_BACKOFF_MS } from './autosave';
import { saveDraftTo, waitNextFrom } from './board-client';
import { LAYER_STRING_NAMES, LAYER_STRING_PREFIX, layerStrings } from './layer-strings';
import type { DraftResult, NextResult } from './board-client';
import { watchNewer, type WatchDocument } from './newer-watch';
import { visitorKey } from './visitor-id';

const TOKEN_A = `pbl_${'a'.repeat(22)}.${'s'.repeat(43)}`;
const TOKEN_B = `pbl_${'b'.repeat(22)}.${'s'.repeat(43)}`;

function memory(): { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void; data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe('the layer strings', () => {
  it('hands the frame every word under its own key names, each from this plugin\'s catalog slice', () => {
    const map = layerStrings();
    expect(Object.keys(map).sort()).toEqual(LAYER_STRING_NAMES.map((name) => `${LAYER_STRING_PREFIX}${name}`).sort());
    for (const [key, text] of Object.entries(map)) expect(text, key).not.toMatch(/^cplug\./);
    expect(map['cplug.reviewboard.layer.note_placeholder']).not.toContain('claude');
  });
});

describe('the visitor key', () => {
  it('is made once per link and kept, 22 url-safe characters, never for a malformed link', () => {
    const win = { localStorage: memory(), crypto };
    const first = visitorKey(win, TOKEN_A);
    expect(first).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(visitorKey(win, TOKEN_A)).toBe(first);
    expect(visitorKey(win, TOKEN_B)).not.toBe(first);
    expect(visitorKey(win, 'garbage')).toBeNull();
    expect([...win.localStorage.data.keys()]).toEqual([`carnivore.publicboard.visitor.${'a'.repeat(22)}`, `carnivore.publicboard.visitor.${'b'.repeat(22)}`]);
  });

  it('keeps one key for the page\'s life when storage refuses', () => {
    const refusing = { getItem: (): string | null => { throw new DOMException('blocked'); }, setItem: (): void => { throw new DOMException('blocked'); } };
    const win = { localStorage: refusing, crypto };
    expect(visitorKey(win, TOKEN_A)).toBe(visitorKey(win, TOKEN_A));
  });
});

describe('the autosave', () => {
  it('writes once after the quiet time with the newest state, and a change during a write goes right after it', async () => {
    vi.useFakeTimers();
    let release: (r: DraftResult) => void = () => undefined;
    const save = vi.fn(() => new Promise<DraftResult>((done) => { release = done; }));
    const auto = createAutosave(save, () => undefined);
    auto.change({ answers: [] });
    auto.change({ answers: [{ prompt: 'a', checked: true }] });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenLastCalledWith({ answers: [{ prompt: 'a', checked: true }] });
    auto.change({ answers: [{ prompt: 'a', checked: false }] });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    release({ kind: 'saved', changed: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(save).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('does not retry a refused write in a loop, reports it, and tries again on flush', async () => {
    vi.useFakeTimers();
    const lights: string[] = [];
    const save = vi.fn(async (): Promise<DraftResult> => ({ kind: 'state', state: 'unavailable' }));
    const auto = createAutosave(save, (light) => lights.push(light));
    auto.change({ answers: [] });
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS * 4);
    expect(save).toHaveBeenCalledTimes(1);
    expect(lights.at(-1)).toBe('failed');
    await auto.flush();
    expect(save).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});

describe('the held wait is the presence heartbeat', () => {
  it('names the visitor key on each ask, and reads a fixed answer\'s retry', async () => {
    const seen: Array<Record<string, string>> = [];
    const fetcher = async (_url: string, init?: RequestInit): Promise<Response> => {
      seen.push(init?.headers as Record<string, string>);
      return new Response('{"state":"fixed","retry":15}', { status: 200 });
    };
    const out = await waitNextFrom('secret', 'r2', fetcher, 'k'.repeat(22));
    expect(seen[0]!['Carnivore-Visitor']).toBe('k'.repeat(22));
    expect(out).toEqual({ kind: 'fixed', retry: 15 });
  });
});

describe('the newer revision watch', () => {
  const visible: WatchDocument = { hidden: false, addEventListener: () => undefined, removeEventListener: () => undefined };

  it('asks again after a quiet answer and reports a newer revision once, then stops', async () => {
    const answers: NextResult[] = [{ kind: 'same', retry: null }, { kind: 'newer', revision: 'r3' }];
    const ask = vi.fn(async (): Promise<NextResult> => answers.shift() ?? { kind: 'same', retry: null });
    const seen: string[] = [];
    watchNewer(ask, (rev) => seen.push(rev), visible, async () => undefined);
    await vi.waitFor(() => expect(seen).toEqual(['r3']));
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it('stops for good on fixed and on ended, and backs off after a fault', async () => {
    for (const end of [{ kind: 'fixed' }, { kind: 'state', state: 'ended' }] as NextResult[]) {
      const ask = vi.fn(async (): Promise<NextResult> => end);
      watchNewer(ask, () => undefined, visible, async () => undefined);
      await vi.waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
      await Promise.resolve();
      expect(ask).toHaveBeenCalledTimes(1);
    }
    const sleeps: number[] = [];
    let n = 0;
    const ask = async (): Promise<NextResult> => (n++ === 0 ? { kind: 'state', state: 'unavailable' } : { kind: 'fixed' });
    watchNewer(ask, () => undefined, visible, async (ms) => { sleeps.push(ms); });
    await vi.waitFor(() => expect(sleeps).toEqual([30000]));
  });

  it('a fixed answer that carries a retry keeps asking after that many seconds: the ask is the presence heartbeat of a pinned link', async () => {
    const answers: NextResult[] = [{ kind: 'fixed', retry: 15 }, { kind: 'fixed', retry: 15 }];
    const ask = vi.fn(async (): Promise<NextResult> => answers.shift() ?? { kind: 'fixed' });
    const sleeps: number[] = [];
    watchNewer(ask, () => undefined, visible, async (ms) => { sleeps.push(ms); });
    await vi.waitFor(() => expect(ask).toHaveBeenCalledTimes(3));
    expect(sleeps).toEqual([15000, 15000]);
  });

  it('asks nothing while the tab is hidden', async () => {
    const ask = vi.fn(async (): Promise<NextResult> => ({ kind: 'fixed' }));
    watchNewer(ask, () => undefined, { ...visible, hidden: true }, async () => undefined);
    await Promise.resolve();
    expect(ask).not.toHaveBeenCalled();
  });
});

describe('the slice 5 review', () => {
  it('an autosave refused as limited waits out the back off before the next write', async () => {
    vi.useFakeTimers();
    try {
      const results: DraftResult[] = [{ kind: 'state', state: 'limited' }, { kind: 'saved', changed: true }];
      const save = vi.fn(async (): Promise<DraftResult> => results.shift() ?? { kind: 'saved', changed: true });
      const auto = createAutosave(save, () => undefined);
      auto.change({ answers: [] });
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
      expect(save).toHaveBeenCalledTimes(1);
      auto.change({ answers: [{ prompt: 'padding', checked: true }] });
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
      expect(save).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(LIMITED_BACKOFF_MS);
      expect(save).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a draft is posted with keepalive, so the last edit lands when the tab closes', async () => {
    const seen: RequestInit[] = [];
    const fetcher = vi.fn(async (_url: string, init: RequestInit): Promise<Response> => {
      seen.push(init);
      return new Response(JSON.stringify({ state: 'saved', changed: true }), { status: 200 });
    });
    await saveDraftTo('pbl_x', 'k'.repeat(22), { revision: 'r1', answers: [] }, fetcher);
    expect(seen[0]?.keepalive).toBe(true);
  });
});

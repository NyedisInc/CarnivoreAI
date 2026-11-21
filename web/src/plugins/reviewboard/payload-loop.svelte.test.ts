import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BoardSidecar, RoundContext } from './board-model';

const sendRoundKept = vi.fn();
const savePayloadDraft = vi.fn(async (..._args: unknown[]): Promise<void> => undefined);
vi.mock('./board-api', () => ({ sendRoundKept: (...a: unknown[]) => sendRoundKept(...a), savePayloadDraft: (...a: unknown[]) => savePayloadDraft(...a) }));

const { PayloadLoop } = await import('./payload-loop.svelte');

const sidecar = { board: { slug: 'b', title: 'board' }, task: { item_id: 7, title_at_link: 'task' } } as unknown as BoardSidecar;
const context = {} as RoundContext;

afterEach(() => {
  vi.unstubAllGlobals();
  sendRoundKept.mockReset();
  savePayloadDraft.mockReset();
  savePayloadDraft.mockResolvedValue(undefined);
});

describe('send on a plain-HTTP LAN page', () => {
  it('reaches the server when crypto.randomUUID is absent (insecure context)', async () => {
    vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => a });
    sendRoundKept.mockResolvedValue({ round: { save: 2 }, delivery: { state: 'posted' } });
    const loop = new PayloadLoop(async () => undefined, () => undefined);
    loop.attach('b', 'r5');
    loop.payload = { picks: { 'aw-1': 'ok' } };
    await loop.send(sidecar, 'r5', context);
    expect(sendRoundKept).toHaveBeenCalledTimes(1);
    expect(sendRoundKept.mock.calls[0]![1].client_round_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4/);
    expect(loop.sending).toBe(false);
    expect(loop.failed).toBe(false);
  });
});

describe('a write queued behind another (u127-01)', () => {
  it('writes the state it was asked to write, to the revision it was asked about, even after the board moved on', async () => {
    let clock = 0;
    const loop = new PayloadLoop(async () => undefined, () => undefined, () => clock);
    loop.attach('b', 'r1');
    loop.pageReady({ id: 'r1', saves: [], draft: null } as never);
    clock = 10_000;
    let release: () => void = () => undefined;
    savePayloadDraft.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));

    loop.received({ picks: { a: 'one' } });
    const first = loop.flush();
    loop.received({ picks: { a: 'two' } });
    const queued = loop.flush(); // queued behind it
    loop.attach('b', 'r2');
    release();
    await Promise.all([first, queued]);

    const writes = savePayloadDraft.mock.calls.map((c) => ({ slug: c[0], revision: (c[1] as { revision: string }).revision, payload: (c[1] as { payload: unknown }).payload }));
    expect(writes).toEqual([
      { slug: 'b', revision: 'r1', payload: { picks: { a: 'one' } } },
      { slug: 'b', revision: 'r1', payload: { picks: { a: 'two' } } },
    ]);
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BoardSidecar, RoundContext } from './board-model';

const sendRoundKept = vi.fn();
vi.mock('./board-api', () => ({ sendRoundKept: (...a: unknown[]) => sendRoundKept(...a), savePayloadDraft: vi.fn(async () => undefined) }));

const { PayloadLoop } = await import('./payload-loop.svelte');

const sidecar = { board: { slug: 'b', title: 'board' }, task: { item_id: 7, title_at_link: 'task' } } as unknown as BoardSidecar;
const context = {} as RoundContext;

afterEach(() => {
  vi.unstubAllGlobals();
  sendRoundKept.mockReset();
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

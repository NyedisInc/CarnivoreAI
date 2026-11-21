import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../sdk';
import type { DraftWire } from './board-model';
import { DraftSync } from './draft-sync';
import { newDraft, setNote } from './tray-model';

const wire = (rev: number, note = ''): DraftWire => ({ ...newDraft('r1', 'cid'), rev, note });

function api(over: Partial<{ get: () => Promise<DraftWire | null>; put: (b: DraftWire) => Promise<DraftWire>; remove: () => Promise<void> }> = {}) {
  return {
    get: vi.fn(async () => null as DraftWire | null),
    put: vi.fn(async (b: DraftWire) => ({ ...b, rev: b.rev + 1 })),
    remove: vi.fn(async () => undefined),
    ...over,
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('saving the draft', () => {
  it('shows an edit at once and saves ONE put a moment later with the rev it read', async () => {
    const a = api();
    const seen: Array<DraftWire | null> = [];
    const sync = new DraftSync(a, (d) => seen.push(d));
    sync.edit((d) => setNote(d ?? wire(0), 'a'));
    sync.edit((d) => setNote(d!, 'ab'));
    expect(seen.at(-1)?.note).toBe('ab');
    expect(a.put).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(700);
    expect(a.put).toHaveBeenCalledTimes(1);
    expect(vi.mocked(a.put).mock.calls[0]![0]).toMatchObject({ rev: 0, note: 'ab' });
    expect(sync.draft?.rev).toBe(1);
    expect(sync.pending).toBe(false);
  });

  it('on a stale rev takes the server rev and sends the same words again once', async () => {
    const stale = new ApiError('stale', 409, null, { detail: { code: 'reviewboard_draft_stale', draft: wire(5, 'other') } });
    const put = vi.fn().mockRejectedValueOnce(stale).mockImplementation(async (b: DraftWire) => ({ ...b, rev: b.rev + 1 }));
    const sync = new DraftSync(api({ put }), () => undefined);
    sync.edit(() => wire(0, 'mine'));
    await sync.flush();
    expect(put).toHaveBeenCalledTimes(2);
    expect(put.mock.calls[1]![0]).toMatchObject({ rev: 5, note: 'mine' });
    expect(sync.draft?.rev).toBe(6);
  });

  it('keeps an edit that could not be saved for the next try', async () => {
    const put = vi.fn().mockRejectedValueOnce(new Error('down')).mockImplementation(async (b: DraftWire) => ({ ...b, rev: 1 }));
    const sync = new DraftSync(api({ put }), () => undefined);
    sync.edit(() => wire(0, 'x'));
    await sync.flush();
    expect(sync.pending).toBe(true);
    await sync.flush();
    expect(sync.pending).toBe(false);
  });

  it('clearing the draft deletes it on the server', async () => {
    const a = api();
    const sync = new DraftSync(a, () => undefined);
    sync.edit(() => wire(0, 'x'));
    await sync.flush();
    sync.edit(() => null);
    await sync.flush();
    expect(a.remove).toHaveBeenCalledTimes(1);
  });
});

describe('another device', () => {
  it('is adopted when nothing local waits, and ignored while an edit waits', async () => {
    const a = api({ get: vi.fn(async () => wire(3, 'phone')) });
    const sync = new DraftSync(a, () => undefined);
    await sync.remoteChanged();
    expect(sync.draft?.note).toBe('phone');
    sync.edit((d) => setNote(d!, 'typing'));
    await sync.remoteChanged();
    expect(sync.draft?.note).toBe('typing');
  });
});

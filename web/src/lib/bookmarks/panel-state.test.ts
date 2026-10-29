import { beforeEach, describe, expect, test, vi } from 'vitest';

const rewindTo = vi.fn();
const branchFrom = vi.fn();
const listBookmarks = vi.fn();
const listTurns = vi.fn();

vi.mock('./api', () => ({
  rewindTo: (...a: unknown[]) => rewindTo(...a),
  branchFrom: (...a: unknown[]) => branchFrom(...a),
  listBookmarks: (...a: unknown[]) => listBookmarks(...a),
  listTurns: (...a: unknown[]) => listTurns(...a),
  addBookmark: vi.fn(),
  deleteBookmark: vi.fn(),
}));

import { BookmarksPanelState } from './panel-state.svelte';

beforeEach(() => {
  vi.clearAllMocks();
  listBookmarks.mockResolvedValue({ bookmarks: [], family: 'claude', conversation: 'c1' });
  listTurns.mockResolvedValue({ turns: [], total: 0 });
});

describe('BookmarksPanelState rewind gate', () => {
  test('an unticked box refuses without a request', async () => {
    const panel = new BookmarksPanelState(7);
    expect(await panel.rewind({ bookmarkId: 1 })).toBe(false);
    expect(rewindTo).not.toHaveBeenCalled();
  });

  test('a ticked box sends confirm true, then unticks', async () => {
    rewindTo.mockResolvedValue({ ok: true, killed_live_pane: true, resumed_copy: true });
    const panel = new BookmarksPanelState(7);
    panel.armed = true;
    expect(await panel.rewind({ entryUuid: 'e1' })).toBe(true);
    expect(rewindTo).toHaveBeenCalledWith(7, { entryUuid: 'e1' }, true);
    expect(panel.armed).toBe(false);
  });

  test('a refused rewind keeps the panel open and shows the reason', async () => {
    rewindTo.mockRejectedValue(new Error('not live'));
    const panel = new BookmarksPanelState(7);
    panel.armed = true;
    expect(await panel.rewind({ bookmarkId: 2 })).toBe(false);
    expect(panel.notice?.error).toBe(true);
  });

  test('branch never needs the arm box', async () => {
    branchFrom.mockResolvedValue({ label: 'api(branch)' });
    const panel = new BookmarksPanelState(7);
    await panel.branch({ bookmarkId: 3 });
    expect(branchFrom).toHaveBeenCalledWith(7, { bookmarkId: 3 });
  });

  test('an ok:false answer shows the server reason as an error, not the rewound wording (u131-02)', async () => {
    rewindTo.mockResolvedValue({ ok: false, detail: 'the session is not live', killed_live_pane: false, resumed_copy: true });
    const panel = new BookmarksPanelState(7);
    panel.armed = true;
    expect(await panel.rewind({ bookmarkId: 2 })).toBe(false);
    expect(panel.notice).toEqual({ text: 'the session is not live', error: true });
  });

  test('an ok:false answer with no detail still says it failed', async () => {
    rewindTo.mockResolvedValue({ ok: false, detail: null, killed_live_pane: false, resumed_copy: true });
    const panel = new BookmarksPanelState(7);
    panel.armed = true;
    await panel.rewind({ bookmarkId: 2 });
    expect(panel.notice?.error).toBe(true);
    expect(panel.notice?.text).not.toMatch(/rewound/);
  });
});

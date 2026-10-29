import { describe, expect, it, vi } from 'vitest';

vi.mock('../i18n/index.svelte', () => ({ t: (k: string) => k }));
vi.mock('../../opscenter/api', () => ({ sessions: { data: [] } }));
vi.mock('../modal', () => ({ openModal: vi.fn() }));
vi.mock('./BookmarksPanel.svelte', () => ({ default: {} }));

describe('row menu bookmark flash', () => {
  it('flashes "bookmarked" with the session name on success and the sentence on failure', async () => {
    const { flashToast, BOOKMARK_TOAST_KIND } = await import('./row-actions');
    const ok = flashToast(true, 'api', '', 1);
    expect(ok).toMatchObject({ kind: BOOKMARK_TOAST_KIND, title: 'bookmarks.saved', body: 'api', local: true });
    expect(flashToast(false, 'api', 'no transcript', 1)).toMatchObject({ title: 'bookmarks.toast.failed', body: 'no transcript' });
  });

  it('says so, and opens nothing, while the listing has no row yet', async () => {
    const { openSessionBookmarks } = await import('./row-actions');
    expect(await openSessionBookmarks('cloude_gone')).toBe(false);
  });
});

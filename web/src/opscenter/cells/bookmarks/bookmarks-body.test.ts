/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({ getPreview: vi.fn(), branchFrom: vi.fn(), rewindTo: vi.fn(), deleteBookmark: vi.fn() }));
vi.mock('../../../lib/bookmarks/api', async (actual) => ({ ...(await actual<typeof import('../../../lib/bookmarks/api')>()), ...api }));
vi.mock('../../../lib/item-settings/store.svelte', () => ({ widgetSetting: (_id: string, key: string) => ({ showPreview: true, previewTurns: 4 })[key] }));

import BookmarksBody from './BookmarksBody.svelte';
import type { BookmarkGroup } from './types';

const mark = { id: 3, label: 'before the refactor', snippet: 's', created_by: 'owner' as const, created_at: '2026-10-10T10:00:00Z',
  session_row_id: 7, session_uuid: 'u', claude_session_uuid: 'c', entry_uuid: 'e', entry_timestamp: '' };
const groups: BookmarkGroup[] = [{ key: 's', label: null, marks: [mark] }];

let handle: Record<string, unknown> | null = null;
async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
  await tick();
  flushSync();
}

beforeEach(() => {
  vi.clearAllMocks();
  api.branchFrom.mockResolvedValue({ label: 'branch' });
  const el = document.createElement('div');
  document.body.append(el);
  handle = mount(BookmarksBody, { target: el, props: { groups, live: () => true } });
});

afterEach(() => {
  if (handle) void unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

describe('bookmarks widget body', () => {
  test('a bookmark row branches by its id and offers no compaction icon, hide or show-hidden key', async () => {
    const rows = document.querySelectorAll('[data-bookmark-row]');
    expect(rows).toHaveLength(1);
    expect(document.querySelector('[data-automatic], [data-compaction-icon], [data-hide], [data-show-hidden]')).toBeNull();
    rows[0]!.querySelector<HTMLButtonElement>('[data-branch]')!.click();
    await settle();
    expect(api.branchFrom).toHaveBeenCalledWith(7, { bookmarkId: 3 });
  });
});

describe('u157-08: delete needs a second press', () => {
  test('one press arms and says so, the second press on the same bookmark deletes', async () => {
    api.deleteBookmark.mockResolvedValue(undefined);
    const del = document.querySelector<HTMLButtonElement>('[data-delete]')!;
    del.click();
    await settle();
    expect(api.deleteBookmark).not.toHaveBeenCalled();
    expect(document.querySelector('.oc-bkm-notice')?.textContent ?? '').not.toBe('');
    del.click();
    await settle();
    expect(api.deleteBookmark).toHaveBeenCalledWith(3);
  });
});

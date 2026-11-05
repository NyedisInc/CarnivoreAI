/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({
  addBookmark: vi.fn(),
  getPreview: vi.fn(),
  listBookmarks: vi.fn(),
  listTurns: vi.fn(),
  branchFrom: vi.fn(),
  rewindTo: vi.fn(),
  rewindFiles: vi.fn(),
  deleteBookmark: vi.fn(),
}));
vi.mock('./api', async (actual) => ({ ...(await actual<typeof import('./api')>()), ...api }));

const settings = vi.hoisted(() => ({ values: { showPreview: true, previewTurns: 4 } as Record<string, unknown> }));
vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: (_id: string, key: string) => settings.values[key] }));

const opened = vi.hoisted(() => vi.fn());
vi.mock('../modal', () => ({ openModal: opened }));
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {} }) }));
vi.mock('../../opscenter/api', () => ({
  sessions: { data: [{ tmux_session: 'cc_one', session_row_id: 7, label: 'one', activity_status: 'idle' }] },
}));

import BookmarksPanel from './BookmarksPanel.svelte';
import { t } from '../i18n/index.svelte';

let handle: Record<string, unknown> | null = null;
const target = (): HTMLElement => {
  const el = document.createElement('div');
  document.body.append(el);
  return el;
};
async function settle(): Promise<void> {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
  await tick();
  flushSync();
}

beforeEach(() => {
  vi.clearAllMocks();
  settings.values = { showPreview: true, previewTurns: 4 };
  api.listBookmarks.mockResolvedValue({
    family: 'claude',
    conversation: 'c1',
    bookmarks: [
      { id: 11, label: 'end of turn', snippet: 's', created_by: 'owner', created_at: '2026-10-10T10:00:00Z', session_row_id: 7,
        files_checkpoint_id: 3, files_unavailable: null },
      { id: 12, label: 'mid turn', snippet: 's', created_by: 'owner', created_at: '2026-10-10T10:00:00Z', session_row_id: 7,
        files_checkpoint_id: null, files_unavailable: 'mid_turn' },
    ],
  });
  api.listTurns.mockResolvedValue({ turns: [{ entry_uuid: 'e9', snippet: 'a past prompt', timestamp: '', number: 1 }], total: 1 });
  api.addBookmark.mockResolvedValue({});
  api.getPreview.mockResolvedValue({
    bookmark_id: 11, conversation: 'c1', turns: 4,
    parts: [{ entry_uuid: 'p1', role: 'user', text: 'fix it', timestamp: '', truncated: false },
      { entry_uuid: 'p2', role: 'assistant', text: 'fixed', timestamp: '', truncated: false }],
  });
});
afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

describe('rewind to a bookmark', () => {
  test('files: a mid-turn bookmark cannot, and its key says why; both goes to the files route', async () => {
    const el = target();
    handle = mount(BookmarksPanel, { target: el, props: { rowId: 7, name: 'one', close: vi.fn() } });
    await settle();
    const modes = [...el.querySelectorAll<HTMLButtonElement>('[data-rewind-mode]')].map((b) => b.dataset.rewindMode);
    expect(modes).toEqual(['conversation', 'files', 'both']);
    el.querySelector<HTMLInputElement>('[data-arm] input, input[data-arm]')!.click();
    el.querySelector<HTMLButtonElement>('[data-rewind-mode="both"]')!.click();
    await settle();
    const keys = [...el.querySelectorAll<HTMLButtonElement>('[data-bookmark-row] [data-rewind]')];
    expect(keys[1]!.disabled).toBe(true);
    expect(keys[1]!.getAttribute('aria-label')).toBe(t('bookmarks.files_mid_turn'));
    expect(keys[0]!.disabled).toBe(false);
    api.rewindFiles.mockResolvedValue({ mode: 'both', conversation: { ok: true }, checkpoint_id: 3, files_restored: false,
      files_error: 'conversation rewound, files not restored', why: 'disk went away', safety_id: null, changed: [], created: [], deleted: [] });
    keys[0]!.click();
    await settle();
    expect(api.rewindFiles).toHaveBeenCalledWith(11, 'both', true);
    expect(api.rewindTo).not.toHaveBeenCalled();
    expect(el.querySelector('[role="status"]')!.textContent).toContain('conversation rewound, files not restored');
  });
});

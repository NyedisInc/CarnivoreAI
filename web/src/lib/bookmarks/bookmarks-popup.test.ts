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

import BookmarkButtons from './BookmarkButtons.svelte';
import BookmarksPanel from './BookmarksPanel.svelte';
import { BookmarkPreviews } from './preview-state.svelte';

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
    bookmarks: [{ id: 11, label: 'before the refactor', snippet: 's', created_by: 'owner', created_at: '2026-10-10T10:00:00Z', session_row_id: 7 }],
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

describe('the session pane bookmark control', () => {
  test('is ONE button, and it opens the bookmarks popup for the session row', async () => {
    handle = mount(BookmarkButtons, { target: target(), props: { sessionName: 'cc_one' } });
    await settle();
    const buttons = document.querySelectorAll('button');
    expect(buttons).toHaveLength(1);
    expect(document.querySelector('[data-bookmark-now]')).toBeNull();
    buttons[0]!.click();
    expect(opened).toHaveBeenCalledTimes(1);
    expect(opened.mock.calls[0]![0]).toBe(BookmarksPanel);
    expect(opened.mock.calls[0]![1]).toMatchObject({ rowId: 7 });
  });

  test('waits, disabled, while the session has no row yet', async () => {
    handle = mount(BookmarkButtons, { target: target(), props: { sessionName: 'cc_unknown' } });
    await settle();
    expect(document.querySelector<HTMLButtonElement>('[data-bookmarks-open]')!.disabled).toBe(true);
  });
});

describe('the bookmarks popup', () => {
  async function openPanel(): Promise<HTMLElement> {
    const el = target();
    handle = mount(BookmarksPanel, { target: el, props: { rowId: 7, name: 'one', close: vi.fn() } });
    await settle();
    return document.body;
  }

  test('adds a bookmark under the typed name from the field at the top, then clears it', async () => {
    const body = await openPanel();
    const form = body.querySelector<HTMLFormElement>('[data-bookmark-add]')!;
    expect(form).not.toBeNull();
    const list = body.querySelector('.bm-panel__list');
    expect(form.compareDocumentPosition(list!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const input = form.querySelector<HTMLInputElement>('[data-bookmark-name]')!;
    input.value = 'before the refactor 2';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    expect(api.addBookmark).toHaveBeenCalledWith(7, undefined, 'before the refactor 2');
    expect(input.value).toBe('');
  });

  function unfoldTurns(body: HTMLElement): void {
    body.querySelector<HTMLButtonElement>('[data-turns-fold]')!.click();
    flushSync();
  }

  test('the section reads "recent turns" and starts folded; a click unfolds it', async () => {
    const body = await openPanel();
    const fold = body.querySelector<HTMLButtonElement>('[data-turns-fold]')!;
    expect(fold.textContent).toContain('recent turns');
    expect(fold.textContent).not.toContain('past turns');
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    expect(body.textContent).not.toContain('a past prompt');
    unfoldTurns(body);
    expect(fold.getAttribute('aria-expanded')).toBe('true');
    expect(body.textContent).toContain('a past prompt');
  });

  test('a compaction point is not a bookmark: a payload carrying one draws no row and no hide or show-hidden key', async () => {
    api.listBookmarks.mockResolvedValue({
      family: 'claude', conversation: 'c1', bookmarks: [],
      compactions: [{ entry_uuid: 'cb', conversation: 'c1', at: '2026-10-10T12:00:00Z', trigger: 'manual', pre_tokens: 9, jsonl_line: 19 }],
    });
    const body = await openPanel();
    expect(body.querySelector('[data-automatic], [data-compaction-icon], [data-hide], [data-show-hidden]')).toBeNull();
    expect(body.textContent).not.toContain('compacted');
  });

  test('every row action is an icon-only button with an aria-label (a tooltip on all but the trash), no words', async () => {
    const body = await openPanel();
    unfoldTurns(body);
    const rows = body.querySelectorAll('[data-bookmark-row]');
    expect(rows.length).toBe(2);
    for (const row of rows) {
      for (const button of row.querySelectorAll('button')) {
        expect(button.textContent?.trim()).toBe('');
        expect(button.getAttribute('aria-label')).toBeTruthy();
        expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label'));
        expect(button.querySelector('svg')).not.toBeNull();
      }
    }
    expect(rows[0]!.querySelectorAll('button')).toHaveLength(4);
    expect(rows[1]!.querySelectorAll('button')).toHaveLength(3);
  });

  test('the eye key shows the preview read with N from the setting, and hides it again', async () => {
    settings.values = { showPreview: true, previewTurns: 2 };
    const body = await openPanel();
    body.querySelector<HTMLButtonElement>('[data-bookmark-preview-toggle]')!.click();
    await settle();
    expect(api.getPreview).toHaveBeenCalledWith(11, 2);
    expect(body.querySelectorAll('[data-bookmark-preview] li')).toHaveLength(2);
    body.querySelector<HTMLButtonElement>('[data-bookmark-preview-toggle]')!.click();
    await settle();
    expect(body.querySelector('[data-bookmark-preview]')).toBeNull();
  });

  test('with the showPreview setting off no preview key is offered', async () => {
    settings.values = { showPreview: false, previewTurns: 4 };
    const body = await openPanel();
    expect(body.querySelector('[data-bookmark-preview-toggle]')).toBeNull();
  });
});

describe('BookmarkPreviews', () => {
  test('asks for N from the setting, and reads again when N changed', async () => {
    const previews = new BookmarkPreviews();
    settings.values = { showPreview: true, previewTurns: 3 };
    await previews.toggle(5);
    expect(api.getPreview).toHaveBeenLastCalledWith(5, 3);
    expect(previews.entry(5)?.status).toBe('ready');
    await previews.toggle(5);
    await previews.toggle(5);
    expect(api.getPreview).toHaveBeenCalledTimes(1);
    await previews.toggle(5);
    settings.values = { showPreview: true, previewTurns: 6 };
    await previews.toggle(5);
    expect(api.getPreview).toHaveBeenLastCalledWith(5, 6);
  });

  test('a refused read is the entry\'s own sentence, not a throw', async () => {
    api.getPreview.mockRejectedValue(new Error('transcript is not on this computer'));
    const previews = new BookmarkPreviews();
    await previews.toggle(5);
    expect(previews.entry(5)).toMatchObject({ status: 'error', error: 'transcript is not on this computer' });
  });
});

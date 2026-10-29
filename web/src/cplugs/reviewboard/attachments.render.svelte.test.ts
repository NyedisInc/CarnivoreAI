/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { BoardAttachment } from './attachment-model';

const api = vi.hoisted(() => ({ fetchAttachments: vi.fn(), fetchAttachmentBlob: vi.fn() }));
vi.mock('./board-api', () => api);
const sdk = vi.hoisted(() => ({ downloadBlob: vi.fn() }));
vi.mock('../sdk', async (importOriginal) => ({ ...(await importOriginal<typeof import('../sdk')>()), ...sdk }));

import AttachmentsKey from './AttachmentsKey.svelte';

const SLUG = '20261013-bottom-bar';
const file = (id: string, name: string, over: Partial<BoardAttachment> = {}): BoardAttachment => ({
  file_id: id, item_id: 7, message_id: 41, name, mime: 'application/pdf', bytes: 1_500_000, sha256: 'a'.repeat(64),
  added_at: '2026-10-14T09:05:00Z', revision: 'r2', url: `/api/v1/cplugs/huddle/items/7/files/${id}`, ...over,
});
const LISTED = [file('ab12cd34', 'spec.pdf'), file('ef56ab78', 'notes.md', { mime: 'text/markdown', bytes: 900, revision: null })];

let app: ReturnType<typeof mount> | null = null;
const props = $state({ slug: SLUG, tick: 0 });

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}
const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector(sel) as T;

beforeEach(async () => {
  URL.createObjectURL = vi.fn(() => 'blob:spec');
  URL.revokeObjectURL = vi.fn();
  api.fetchAttachments.mockResolvedValue({ slug: SLUG, attachments: LISTED });
  api.fetchAttachmentBlob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }));
  props.tick = 0;
  app = mount(AttachmentsKey, { target: document.body, props });
  await settle();
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.replaceChildren();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('the paperclip key', () => {
  it('wears the count the GET answered and lists every file newest first with its size, date and revision', async () => {
    expect(api.fetchAttachments).toHaveBeenCalledWith(SLUG);
    expect(q('[data-attachments-count]').textContent).toBe('2');
    expect(q('[data-attachments-fold]')).toBeNull();
    q('[data-attachments-key]').click();
    await settle();
    const rows = [...document.querySelectorAll('[data-attachment]')];
    expect(rows.map((r) => r.querySelector('[data-clip-name]')?.textContent)).toEqual(['notes.md', 'spec.pdf']);
    expect(rows[0]!.querySelector('[data-clip-meta]')?.textContent).toMatch(/^900 b \u00b7 2026-10-1\d \d\d:\d\d$/);
    expect(rows[1]!.querySelector('[data-clip-meta]')?.textContent).toMatch(/^1\.4 mb \u00b7 .+ \u00b7 r2$/);
    expect(rows.every((r) => r.querySelector('[data-attachment-open]') && r.querySelector('[data-attachment-download]'))).toBe(true);
  });

  it('download reads the bytes through the app route and saves them under the file name', async () => {
    q('[data-attachments-key]').click();
    await settle();
    q('[data-attachment="ab12cd34"] [data-attachment-download]').click();
    await settle();
    expect(api.fetchAttachmentBlob).toHaveBeenCalledWith('/cplugs/huddle/items/7/files/ab12cd34');
    expect(sdk.downloadBlob).toHaveBeenCalledWith('spec.pdf', expect.any(Blob));
  });

  it('open takes a tab at the press and points it at the bytes once they arrive', async () => {
    const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn() };
    vi.stubGlobal('open', vi.fn(() => tab));
    q('[data-attachments-key]').click();
    await settle();
    q('[data-attachment="ab12cd34"] [data-attachment-open]').click();
    await settle();
    expect(window.open).toHaveBeenCalledWith('', '_blank');
    expect(tab.opener).toBeNull();
    expect(tab.location.href).toBe('blob:spec');
  });

  it('a file with no route (the huddle is off) offers no keys, and a boards push reads the list again', async () => {
    api.fetchAttachments.mockResolvedValue({ slug: SLUG, attachments: [...LISTED, file('99aa88bb', 'late.png', { url: null })] });
    props.tick = 1;
    await settle();
    expect(api.fetchAttachments).toHaveBeenCalledTimes(2);
    expect(q('[data-attachments-count]').textContent).toBe('3');
    q('[data-attachments-key]').click();
    await settle();
    const late = q('[data-attachment="99aa88bb"]');
    expect(late.querySelector('[data-attachment-open]')).toBeNull();
    expect(late.querySelector('[data-attachment-offline]')).not.toBeNull();
  });
});

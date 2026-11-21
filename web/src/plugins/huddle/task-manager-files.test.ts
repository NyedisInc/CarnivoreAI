/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  calls: [] as Array<{ path: string; method: string; body: unknown }>,
  uploadFails: false,
  nextId: 0,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (init.body instanceof FormData) {
        const file = init.body.get('file') as File;
        server.calls.push({ path, method, body: file.name });
        if (server.uploadFails) throw new Error('file exceeds maximum size of 50 MB');
        server.nextId += 1;
        return { id: `ab12cd3${server.nextId}`, name: file.name, mime: file.type, size: file.size };
      }
      server.calls.push({ path, method, body: init.body ? JSON.parse(String(init.body)) : null });
      if (/\/files\/[0-9a-f]{8}$/.test(path)) return new File(['png'], 'a.png', { type: 'image/png' });
      if (path === '/cplugs/huddle/focus') return { focus: null };
      return {};
    },
  };
});

import { carriesFiles, filesOf, readyIds, sizeLabel, MAX_PER_REPLY } from './task-manager-files';
import { createAttachments } from './task-manager-attachments.svelte';
import HuddleReply from './HuddleReply.svelte';
import HuddleThread from './HuddleThread.svelte';

const file = (name: string, type = 'text/plain', body = 'x') => new File([body], name, { type });

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

describe('the paste and drop model', () => {
  test('only a transfer that carries files is ours; dragged text is left alone', () => {
    expect(carriesFiles({ types: ['Files'] })).toBe(true);
    expect(carriesFiles({ types: ['text/plain'] })).toBe(false);
    expect(carriesFiles(null)).toBe(false);
  });

  test('files come from `files`, else from file items (a screenshot), and plain text yields none', () => {
    const a = file('a.png', 'image/png');
    expect(filesOf({ files: [a] })).toEqual([a]);
    expect(filesOf({ files: [], items: [{ kind: 'file', getAsFile: () => a }, { kind: 'string', getAsFile: () => null }] })).toEqual([a]);
    expect(filesOf({ files: [], items: [{ kind: 'string', getAsFile: () => null }] })).toEqual([]);
    expect(filesOf(null)).toEqual([]);
  });

  test('sizes read short and lowercase', () => {
    expect([sizeLabel(512), sizeLabel(12 * 1024), sizeLabel(1.5 * 1024 * 1024)]).toEqual(['512 b', '12 kb', '1.5 mb']);
  });

  test('a send names only the ready chips', () => {
    expect(readyIds([{ status: 'ready', ref: { id: 'a' } }, { status: 'uploading' }, { status: 'failed' }, { status: 'ready', ref: { id: 'b' } }])).toEqual(['a', 'b']);
  });
});

describe('the chips', () => {
  test('uploading then ready; busy until every upload lands; ids in order', async () => {
    const gates: Array<(v: { id: string; name: string; mime: string; size: number }) => void> = [];
    const files = createAttachments(() => new Promise((resolve) => { gates.push(resolve); }));
    files.add([file('a.txt'), file('b.txt')]);
    expect(files.chips.map((c) => c.status)).toEqual(['uploading', 'uploading']);
    expect(files.busy).toBe(true);
    gates[1]?.({ id: 'bbbbbbbb', name: 'b.txt', mime: 'text/plain', size: 1 });
    gates[0]?.({ id: 'aaaaaaaa', name: 'a.txt', mime: 'text/plain', size: 1 });
    await settle();
    expect(files.busy).toBe(false);
    expect(files.ids).toEqual(['aaaaaaaa', 'bbbbbbbb']);
  });

  test('a refused upload is a failed chip carrying the reason, and is never sent', async () => {
    const files = createAttachments(() => Promise.reject(new Error('empty file payload')));
    files.add([file('a.txt')]);
    await settle();
    expect(files.chips[0]).toMatchObject({ status: 'failed', error: 'empty file payload' });
    expect(files.ids).toEqual([]);
  });

  test('remove drops a chip, and an upload that lands after is not brought back', async () => {
    let finish: (v: { id: string; name: string; mime: string; size: number }) => void = () => {};
    const files = createAttachments(() => new Promise((resolve) => { finish = resolve; }));
    files.add([file('a.txt')]);
    files.remove(files.chips[0]?.key ?? -1);
    finish({ id: 'aaaaaaaa', name: 'a.txt', mime: 'text/plain', size: 1 });
    await settle();
    expect(files.chips).toEqual([]);
    expect(files.ids).toEqual([]);
  });

  test('a reply carries at most MAX_PER_REPLY files', () => {
    const files = createAttachments(() => new Promise(() => {}));
    files.add(Array.from({ length: MAX_PER_REPLY + 4 }, (_, i) => file(`f${i}.txt`)));
    expect(files.chips).toHaveLength(MAX_PER_REPLY);
  });
});

describe('the reply box and the thread', () => {
  let app: ReturnType<typeof mount> | null = null;
  const item = {
    id: 5, list: 'all', text: 't', note: '', position: 1, created_by: 'joe', state: 'open', kind: '', number: 1, revision: 1,
    created_seq: 1, seq: 1, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open',
  } as never;

  beforeEach(() => {
    server.calls = [];
    server.uploadFails = false;
    server.nextId = 0;
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:thumb', revokeObjectURL: () => {} }));
  });
  afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  function transfer(files: File[]): unknown {
    return { files, items: [], types: ['Files'] };
  }

  test('a pasted file uploads at once, shows a chip, and a files-only send posts no text', async () => {
    app = mount(HuddleReply, { target: document.body, props: { item, noSend: true } });
    const box = document.querySelector<HTMLTextAreaElement>('[data-huddle-reply]')!;
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: transfer([file('shot.png', 'image/png')]) });
    box.dispatchEvent(paste);
    expect(paste.defaultPrevented).toBe(true);
    await settle();
    expect(server.calls[0]).toMatchObject({ path: '/cplugs/huddle/items/5/files', method: 'POST', body: 'shot.png' });
    expect(document.querySelector('[data-task-manager-pending-file]')?.getAttribute('data-state')).toBe('ready');
    const send = document.querySelector<HTMLButtonElement>('.hdt-send')!;
    expect(send.disabled).toBe(false);
    send.click();
    await settle();
    const post = server.calls.find((c) => c.path === '/cplugs/huddle/items/5/messages');
    expect(post?.body).toEqual({ text: '', files: ['ab12cd31'], client_id: expect.any(String) });
    expect(document.querySelector('[data-task-manager-pending-file]')).toBeNull();
  });

  test('pending chips sit outside the framed box, so the text stays editable (#2694)', async () => {
    app = mount(HuddleReply, { target: document.body, props: { item, noSend: true } });
    const box = document.querySelector<HTMLTextAreaElement>('[data-huddle-reply]')!;
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: transfer([file('shot.png', 'image/png')]) });
    box.dispatchEvent(paste);
    await settle();
    const chips = document.querySelector('[data-task-manager-pending-files]')!;
    expect(chips).not.toBeNull();
    expect(chips.closest('form')).toBeNull();
    expect(chips.parentElement).toBe(box.closest('form')!.parentElement);
  });

  test('a text paste is left to the browser', async () => {
    app = mount(HuddleReply, { target: document.body, props: { item, noSend: true } });
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: { files: [], items: [], types: ['text/plain'] } });
    document.querySelector('[data-huddle-reply]')!.dispatchEvent(paste);
    expect(paste.defaultPrevented).toBe(false);
    expect(server.calls).toEqual([]);
  });

  test('a drop uploads, the remove key drops the chip, and an empty box with no files cannot send', async () => {
    app = mount(HuddleReply, { target: document.body, props: { item, noSend: true } });
    expect(document.querySelector<HTMLButtonElement>('.hdt-send')!.disabled).toBe(true);
    const form = document.querySelector('form')!;
    const over = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(over, 'dataTransfer', { value: transfer([]) });
    form.dispatchEvent(over);
    expect(over.defaultPrevented).toBe(true);
    const drop = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: transfer([file('notes.pdf', 'application/pdf')]) });
    form.dispatchEvent(drop);
    await settle();
    expect(document.querySelectorAll('[data-task-manager-pending-file]')).toHaveLength(1);
    document.querySelector<HTMLButtonElement>('[data-task-manager-pending-remove]')!.click();
    await settle();
    expect(document.querySelector('[data-task-manager-pending-file]')).toBeNull();
    expect(document.querySelector<HTMLButtonElement>('.hdt-send')!.disabled).toBe(true);
  });

  test('a refused upload shows the server reason on its chip', async () => {
    server.uploadFails = true;
    app = mount(HuddleReply, { target: document.body, props: { item, noSend: true } });
    const drop = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: transfer([file('big.bin')]) });
    document.querySelector('form')!.dispatchEvent(drop);
    await settle();
    const chip = document.querySelector('[data-task-manager-pending-file]')!;
    expect(chip.getAttribute('data-state')).toBe('failed');
    expect(chip.textContent).toContain('50 MB');
  });

  test('the thread draws a reply\'s image as a thumbnail and its other file as a chip, with no empty text bubble', async () => {
    const withFiles = {
      ...(item as object), thread: [{
        id: 9, item_id: 5, author: 'joe', kind: 'reply', text: '', answered: false, created_at: 1, seq: 1,
        files: [{ id: 'ab12cd34', name: 'a.png', mime: 'image/png', size: 3, image: true }, { id: 'ab12cd35', name: 'notes.pdf', mime: 'application/pdf', size: 2048, image: false }],
      }],
    } as never;
    app = mount(HuddleThread, { target: document.body, props: { item: withFiles, closed: true } });
    await settle();
    expect(document.querySelector('[data-task-manager-file-open="ab12cd34"] img')?.getAttribute('src')).toBe('blob:thumb');
    const chip = document.querySelector('[data-task-manager-file-save="ab12cd35"]')!;
    expect(chip.textContent).toContain('notes.pdf');
    expect(chip.textContent).toContain('2 kb');
    expect(document.querySelector('[data-task-manager-message] .hdt-text')).toBeNull();
  });
});

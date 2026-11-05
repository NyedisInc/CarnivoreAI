/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls = vi.hoisted(() => ({ added: [] as Array<{ text: string; ids: string[] }>, staged: [] as string[], hold: null as Promise<void> | null }));
vi.mock('./task-manager-files-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./task-manager-files-api')>()),
  stageFile: async (list: string, file: File) => { calls.staged.push(`${list}:${file.name}`); await calls.hold; return { id: 'ab12cd34', name: file.name, mime: 'text/plain', size: file.size }; },
}));
vi.mock('./huddle.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('./huddle.svelte')>();
  return { ...real, addItem: async (text: string, ids: string[] = []) => { calls.added.push({ text, ids }); return 'queued'; } };
});
vi.mock('./task-submit', async (importOriginal) => ({ ...(await importOriginal<typeof import('./task-submit')>()), submitNow: async (_list: string, save: () => Promise<unknown>) => { await save(); } }));

import HuddleBody from './HuddleBody.svelte';
import { huddle } from './huddle.svelte';

const apps: object[] = [];
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  calls.added.length = 0;
  calls.staged.length = 0;
  calls.hold = null;
});

function draw(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(HuddleBody, { target, props: { popout: true } }));
  flushSync();
  return target;
}

function pasteFile(field: HTMLElement, file: File): ClipboardEvent {
  const event = new Event('paste', { bubbles: true, cancelable: true }) as ClipboardEvent;
  Object.defineProperty(event, 'clipboardData', { value: { files: [file], items: [], types: ['Files'] } });
  field.dispatchEvent(event);
  return event;
}

describe('add row paste', () => {
  test('a pasted file is a removable chip outside the field and rides the add', async () => {
    const body = draw();
    const field = body.querySelector('[data-task-manager-add]') as HTMLInputElement;
    const form = body.querySelector('[data-task-manager-add-form]') as HTMLFormElement;
    const row = body.querySelector('.hd-add-row') as HTMLElement;
    expect(body.querySelector('[data-task-manager-pending-files]')).toBeNull();
    const event = pasteFile(field, new File(['hello'], 'notes.txt', { type: 'text/plain' }));
    expect(event.defaultPrevented).toBe(true);
    flushSync();
    await tick();
    await tick();
    const chips = body.querySelector('[data-task-manager-pending-files]') as HTMLElement;
    expect(chips).not.toBeNull();
    expect(form.contains(chips) && !row.contains(chips)).toBe(true);
    expect(chips.textContent).toContain('notes.txt');
    expect(field.value).toBe('');
    field.value = 'look at this';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    form.requestSubmit();
    await tick();
    await tick();
    expect(calls.added).toEqual([{ text: 'look at this', ids: ['ab12cd34'] }]);
    expect(body.querySelector('[data-task-manager-pending-files]')).toBeNull();
  });

  test('a chip can be removed before the send', async () => {
    const body = draw();
    pasteFile(body.querySelector('[data-task-manager-add]') as HTMLElement, new File(['x'], 'a.txt'));
    flushSync();
    await tick();
    await tick();
    (body.querySelector('[data-task-manager-pending-remove]') as HTMLButtonElement).click();
    flushSync();
    expect(body.querySelector('[data-task-manager-pending-files]')).toBeNull();
  });
});

describe('add row staging', () => {
  test('Enter while a file is still staging adds nothing; it adds once the file is staged', async () => {
    let release = (): void => {};
    calls.hold = new Promise<void>((resolve) => { release = resolve; });
    const body = draw();
    const field = body.querySelector('[data-task-manager-add]') as HTMLInputElement;
    pasteFile(field, new File(['x'], 'slow.txt'));
    field.value = 'look';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await tick();
    expect(calls.added).toEqual([]);
    release();
    await tick();
    await tick();
    await tick();
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await tick();
    await tick();
    expect(calls.added).toEqual([{ text: 'look', ids: ['ab12cd34'] }]);
  });

  test('changing the add target drops the chips (their files were staged for the old list)', async () => {
    const body = draw();
    huddle.addTarget = 'all';
    flushSync();
    pasteFile(body.querySelector('[data-task-manager-add]') as HTMLElement, new File(['x'], 'a.txt'));
    flushSync();
    await tick();
    await tick();
    expect(body.querySelector('[data-task-manager-pending-files]')).not.toBeNull();
    huddle.addTarget = '12';
    flushSync();
    await tick();
    expect(body.querySelector('[data-task-manager-pending-files]')).toBeNull();
  });
});

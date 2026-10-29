/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls = vi.hoisted(() => ({ sent: [] as Array<{ text: string; quiet: boolean }> }));
vi.mock('./huddle.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('./huddle.svelte')>();
  return { ...real, reply: async (_item: unknown, text: string, _ids: unknown, _tell: unknown, quiet: boolean) => { calls.sent.push({ text, quiet: !!quiet }); return true; } };
});

vi.mock('./task-submit', async (importOriginal) => ({ ...(await importOriginal<typeof import('./task-submit')>()), submitNow: async (_list: string, save: () => Promise<unknown>) => { await save(); } }));

import HuddleReply from './HuddleReply.svelte';
import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
import type { HuddleItem } from './huddle-model';

const SPLIT: BodyOptions = { ...DEFAULT_BODY_OPTIONS, tabbedDetail: true, replySplit: true };
const item = { id: 5, list: 'all', thread: [], unread: true } as unknown as HuddleItem;
const apps: object[] = [];

afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  calls.sent.length = 0;
});

function draw(options?: BodyOptions): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(HuddleReply, { target, props: { item }, context: new Map(options ? [[BODY_OPTIONS, options]] : []) }));
  flushSync();
  return target;
}

async function type(box: HTMLElement, text: string): Promise<void> {
  const field = box.querySelector('[data-huddle-reply]') as HTMLTextAreaElement;
  field.value = text;
  field.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  await tick();
}

const main = (box: HTMLElement) => box.querySelector('.oc-split > [data-btn]') as HTMLButtonElement;
const picker = (box: HTMLElement) => box.querySelector('.oc-split__select') as HTMLSelectElement;

describe('split reply box', () => {
  test('one split button replaces the reply, comment and mark read keys', () => {
    const box = draw(SPLIT);
    expect(main(box).textContent).toBe('reply');
    expect(box.querySelector('[data-task-manager-comment]')).toBeNull();
    expect(box.querySelector('[data-task-manager-mark-read]')).toBeNull();
    expect([...picker(box).options].map((o) => o.value)).toEqual(['reply', 'comment']);
  });

  test('reply sends a reply; the caret switches to comment, which sends a quiet comment; after a send it is reply again', async () => {
    const box = draw(SPLIT);
    await type(box, 'first');
    main(box).click();
    await vi.waitFor(() => expect(calls.sent).toEqual([{ text: 'first', quiet: false }]));
    await new Promise((done) => setTimeout(done, 0));

    picker(box).value = 'comment';
    picker(box).dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(main(box).textContent).toBe('comment');
    await type(box, 'a note');
    main(box).click();
    await vi.waitFor(() => expect(calls.sent.at(-1)).toEqual({ text: 'a note', quiet: true }));
    flushSync();
    expect(main(box).textContent).not.toBe('comment');
    expect(picker(box).value).toBe('reply');
  });

  test('Enter sends what the split says: a comment while comment is picked', async () => {
    const box = draw(SPLIT);
    picker(box).value = 'comment';
    picker(box).dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    await type(box, 'quiet one');
    (box.querySelector('[data-huddle-reply]') as HTMLTextAreaElement).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(calls.sent).toEqual([{ text: 'quiet one', quiet: true }]));
  });

  test('the box grows to three lines and then scrolls, only in the split host', () => {
    const sheet = readFileSync(resolve(process.cwd(), 'src/cplugs/huddle/HuddleReply.svelte'), 'utf8');
    expect(sheet).toMatch(/\.hdt-input--rows3 \{[^}]*max-height: calc\(3lh \+ 2 \* var\(--oc-space-0-5\)\);[^}]*overflow-y: auto/);
    expect(draw(SPLIT).querySelector('[data-huddle-reply]')?.classList.contains('hdt-input--rows3')).toBe(true);
    expect(draw().querySelector('[data-huddle-reply]')?.classList.contains('hdt-input--rows3')).toBe(false);
  });

  test('every other host keeps its reply and comment keys, and its mark read', () => {
    const box = draw();
    expect(box.querySelector('.oc-split')).toBeNull();
    expect(box.querySelector('[data-task-manager-comment="5"]')).not.toBeNull();
    expect(box.querySelector('[data-task-manager-mark-read="5"]')).not.toBeNull();
  });
});

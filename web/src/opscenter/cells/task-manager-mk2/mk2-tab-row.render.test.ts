/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const markRead = vi.hoisted(() => vi.fn(async () => {}));
const putBack = vi.hoisted(() => vi.fn());
const heldRead = vi.hoisted(() => vi.fn((task: { unread: boolean }) => { task.unread = false; return { undo: () => { task.unread = true; putBack(); }, send: markRead }; }));
vi.mock('../../../cplugs/huddle/huddle.svelte', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../../cplugs/huddle/huddle.svelte')>()), heldRead }));

import Mk2MarkRead from './Mk2MarkRead.svelte';
import { markReadHolds, undoMarkRead } from './mk2-mark-read.svelte';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

const item = (id: number, unread = true) => ({ id, list: '7', text: 'x', state: 'open', thread: [], unread }) as unknown as HuddleItem;
const apps: object[] = [];

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  for (const id of Object.keys(markReadHolds)) undoMarkRead(Number(id));
  markRead.mockClear();
  putBack.mockClear();
  vi.useRealTimers();
});

function draw(task: HuddleItem): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(Mk2MarkRead, { target, props: { item: task } }));
  flushSync();
  return target;
}
const button = (box: HTMLElement) => box.querySelector('[data-task-manager-mark-read]') as HTMLButtonElement | null;

describe('mark read with a five second undo', () => {
  test('a press asks nothing, counts down on the button, and sends the mark when the count ends', () => {
    const box = draw(item(5));
    expect(button(box)!.textContent).toBe('mark read');
    button(box)!.click();
    flushSync();
    expect(markRead).not.toHaveBeenCalled();
    expect(button(box)!.textContent).toBe('undo (5)');
    vi.advanceTimersByTime(2000);
    flushSync();
    expect(button(box)!.textContent).toBe('undo (3)');
    vi.advanceTimersByTime(3000);
    flushSync();
    expect(markRead).toHaveBeenCalledTimes(1);
  });

  test('undo before the count ends sends nothing, ever', () => {
    const box = draw(item(6));
    button(box)!.click();
    flushSync();
    vi.advanceTimersByTime(2000);
    button(box)!.click();
    flushSync();
    vi.advanceTimersByTime(10000);
    expect(markRead).not.toHaveBeenCalled();
    expect(button(box)!.textContent).toBe('mark read');
  });

  test('closing the row during the count does not drop the mark', () => {
    const task = item(7);
    const box = draw(task);
    button(box)!.click();
    unmount(apps.pop()!, { outro: false });
    vi.advanceTimersByTime(5000);
    expect(markRead).toHaveBeenCalledTimes(1);
  });

  test('a press reads the task right away, before the count ends, and the button stays as the undo', () => {
    const task = item(9);
    const box = draw(task);
    button(box)!.click();
    flushSync();
    expect(task.unread).toBe(false);
    expect(markRead).not.toHaveBeenCalled();
    expect(button(box)!.textContent).toBe('undo (5)');
  });

  test('undo puts the unread mark back and still sends nothing', () => {
    const task = item(10);
    const box = draw(task);
    button(box)!.click();
    flushSync();
    button(box)!.click();
    flushSync();
    expect(putBack).toHaveBeenCalledTimes(1);
    expect(task.unread).toBe(true);
    vi.advanceTimersByTime(10000);
    expect(markRead).not.toHaveBeenCalled();
  });

  test('after the write goes out the view is not put back', () => {
    const task = item(11);
    draw(task);
    button(document.body)!.click();
    vi.advanceTimersByTime(5000);
    expect(markRead).toHaveBeenCalledTimes(1);
    expect(putBack).not.toHaveBeenCalled();
  });

  test('a read task with no hold draws nothing', () => {
    expect(button(draw(item(8, false)))).toBeNull();
  });
});

describe('the strip at a narrow width (round 9c: the undo button overlapped the last tab label at 380)', () => {
  const css = readFileSync('src/opscenter/cells/task-manager-mk2/mk2-design.css', 'utf8');
  test('the tabs go to icons while the strip is too narrow for four labels and the control, and the control keeps one width through its count', () => {
    expect(css).toMatch(/@container oc-ptabs \(max-width: 420px\)[^}]*\{[^}]*oc-ptab__icon[^}]*display: inline-flex/s);
    expect(css).toMatch(/\[data-task-manager-mark-read\]\s*\{[^}]*min-inline-size: calc\(9ch/);
  });
});

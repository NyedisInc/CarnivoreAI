/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import * as keeper from './task-manager-scroll-keep';
import { anchorsOf, createScrollKeeper } from './task-manager-scroll-keep';

const ROW_PX = 40;
const HEAD_PX = 30;
const realRect = Element.prototype.getBoundingClientRect;
let stop: (() => void) | null = null;

afterEach(() => {
  stop?.(); stop = null;
  document.body.innerHTML = '';
  Element.prototype.getBoundingClientRect = realRect;
});

function modelLayout(): void {
  Element.prototype.getBoundingClientRect = function rect(this: Element): DOMRect {
    const make = (top: number, height: number): DOMRect => ({ top, bottom: top + height, left: 0, right: 100, width: 100, height, x: 0, y: top, toJSON: () => ({}) });
    const box = this.closest('[data-box]') as HTMLElement | null;
    if (this.matches('[data-box]')) return make(0, 300);
    if (!box) return make(0, 0);
    let y = 0;
    for (const el of box.querySelectorAll<HTMLElement>('[data-huddle-item], [data-task-manager-level]')) {
      const header = el.hasAttribute('data-task-manager-level');
      const height = header ? HEAD_PX : ROW_PX;
      if (el === this) return make(header && el.hasAttribute('data-stuck') ? Number(el.getAttribute('data-stuck')) : y - box.scrollTop, height);
      y += height;
    }
    return make(0, 0);
  };
}

function build(sections: number[][], stuckHeader = false): HTMLElement {
  const box = document.createElement('div');
  box.setAttribute('data-box', '');
  sections.forEach((ids, n) => {
    const sec = document.createElement('div');
    const head = document.createElement('div');
    head.setAttribute('data-task-manager-level', 'status');
    if (stuckHeader && n === 0) head.setAttribute('data-stuck', '0');
    sec.appendChild(head);
    for (const id of ids) { const row = document.createElement('div'); row.setAttribute('data-huddle-item', String(id)); sec.appendChild(row); }
    box.appendChild(sec);
  });
  document.body.appendChild(box);
  return box;
}
const rowTop = (box: HTMLElement, id: number): number => (box.querySelector(`[data-huddle-item="${id}"]`) as HTMLElement).getBoundingClientRect().top;
const settle = async (): Promise<void> => { for (let i = 0; i < 4; i += 1) await Promise.resolve(); };
function scrollTo(box: HTMLElement, to: number): void { box.scrollTop = to; box.dispatchEvent(new Event('scroll')); }

describe('the keeper holds the screen when the row he reads itself moves (round 9)', () => {
  test('the row he reads re-filed into another section: the list does not scroll and the row above it stays put', async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 100);
    const reading = Number(anchorsOf(box)[0]?.id);
    const above = rowTop(box, reading - 1);
    const el = box.querySelector(`[data-huddle-item="${reading}"]`) as HTMLElement;
    (box.children[1] as HTMLElement).appendChild(el);
    await settle();
    expect(box.scrollTop).toBe(100);
    expect(rowTop(box, reading - 1)).toBe(above);
  });

  test('a row he reads that the list moved others round (its element kept) is not followed down', async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 100);
    const reading = box.querySelector(`[data-huddle-item="${anchorsOf(box)[0]?.id}"]`) as HTMLElement;
    reading.before(reading.nextElementSibling as HTMLElement, reading.nextElementSibling?.nextElementSibling as HTMLElement);
    await settle();
    expect(box.scrollTop).toBe(100);
  });
});

describe('the row he reads is the first one showing below the sticky headers', () => {
  test('a row cut by a stuck header is the row he reads; a row hidden under it is not', () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8]], true);
    box.scrollTop = 100;
    const first = anchorsOf(box)[0];
    expect(first?.id).toBe('3');
    const rect = (first?.el as HTMLElement).getBoundingClientRect();
    expect(rect.top).toBeLessThan(HEAD_PX);
    expect(rect.bottom).toBeGreaterThan(HEAD_PX);
    expect(anchorsOf(box).slice(1, 3).map((a) => a.id)).toEqual(['2', '1']);
  });
});

describe('round 7 part 4 (live, 2026-10-22: "if i scroll all the way up, at a period it will scroll all the way down")', () => {
  test('a section re-sorted with the rows inside it (their neighbors unchanged) is not followed: the list does not travel with it', async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 60);
    expect(anchorsOf(box).every((a) => Number(a.id) <= 10)).toBe(true);
    box.appendChild(box.children[0] as HTMLElement);
    await settle();
    expect(box.scrollTop).toBe(60);
  });

  test('within a few px of the top the keeper never moves the list, even with rows recorded', async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 2);
    const row = document.createElement('div');
    row.setAttribute('data-huddle-item', '99');
    (box.children[0] as HTMLElement).insertBefore(row, box.querySelector('[data-huddle-item]'));
    await settle();
    expect(box.scrollTop).toBe(2);
  });

  test('a single correction is exactly the layout change above an unmoved row', async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 100);
    const watched = rowTop(box, 6);
    box.querySelector('[data-huddle-item="1"]')?.remove();
    await settle();
    expect(box.scrollTop).toBe(100 - ROW_PX);
    expect(rowTop(box, 6)).toBe(watched);
  });

  test("the keeper's own correction is told apart from the owner's scroll, once", async () => {
    modelLayout();
    const box = build([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]);
    stop = createScrollKeeper(box);
    scrollTo(box, 100);
    expect(keeper.isKeeperScroll?.(box)).toBe(false);
    box.querySelector('[data-huddle-item="1"]')?.remove();
    await settle();
    expect(keeper.isKeeperScroll?.(box)).toBe(true);
    expect(keeper.isKeeperScroll?.(box)).toBe(false);
  });
});

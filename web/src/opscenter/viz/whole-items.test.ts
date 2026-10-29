/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { WHOLE_OFF_ATTR, wholeItems } from './whole-items';

afterEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals(); });

function list(room: number, row: number, count: number): HTMLElement {
  const ul = document.createElement('ul');
  for (let i = 0; i < count; i += 1) ul.append(document.createElement('li'));
  document.body.append(ul);
  ul.getBoundingClientRect = () => ({ top: 0, bottom: room, height: room, left: 0, right: 100, width: 100, x: 0, y: 0, toJSON: () => ({}) });
  [...ul.children].forEach((item, at) => {
    (item as HTMLElement).getBoundingClientRect = () => ({ top: at * row, bottom: (at + 1) * row, height: row, left: 0, right: 100, width: 100, x: 0, y: at * row, toJSON: () => ({}) });
  });
  return ul;
}

const off = (ul: HTMLElement): boolean[] => [...ul.children].map((item) => item.hasAttribute(WHOLE_OFF_ATTR) && (item as HTMLElement).style.visibility === 'hidden');

describe('wholeItems', () => {
  test('rows cut by the box edge, and all after, are marked off; whole rows stay', () => {
    const ul = list(70, 30, 4);
    wholeItems(ul);
    expect(off(ul)).toEqual([false, false, true, true]);
  });

  test('a box too short for even one row marks every row off (never half a row)', () => {
    const ul = list(20, 30, 3);
    wholeItems(ul);
    expect(off(ul)).toEqual([true, true, true]);
  });

  test('every row fits: nothing is marked', () => {
    const ul = list(200, 30, 3);
    wholeItems(ul);
    expect(off(ul)).toEqual([false, false, false]);
  });

  test('disabled shows every row, and enabling again re-measures', () => {
    const ul = list(70, 30, 4);
    const action = wholeItems(ul, { enabled: false });
    expect(off(ul)).toEqual([false, false, false, false]);
    action.update({ enabled: true });
    expect(off(ul)).toEqual([false, false, true, true]);
  });
});

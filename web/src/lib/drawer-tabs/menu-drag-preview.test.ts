/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { menuDragActive, onMenuPointerDown, type MenuDragHost } from './menu-drag';

let commit: ReturnType<typeof vi.fn<(ids: string[]) => void>>;
let host: MenuDragHost;
const ROW_H = 30;

beforeEach(() => {
  document.body.innerHTML = '<ul data-menu-zones><li data-menu-row="a"><b>a</b></li><li data-menu-row="b"><b>b</b></li><li data-menu-row="c"><b>c</b></li></ul>';
  const rectOf = (el: Element): DOMRect => {
    const li = el.closest('li') ?? el;
    const lines = [...document.querySelectorAll('li[data-menu-row]')].filter((x) => (x as HTMLElement).style.display !== 'none');
    const at = Math.max(0, lines.indexOf(li));
    return { top: at * ROW_H, bottom: at * ROW_H + ROW_H, left: 0, right: 40, width: 40, height: ROW_H, x: 0, y: at * ROW_H, toJSON: () => ({}) } as DOMRect;
  };
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) { return rectOf(this); });
  commit = vi.fn<(ids: string[]) => void>();
  host = { ids: () => ['a', 'b', 'c'], commit };
  document.querySelector('ul')!.addEventListener('pointerdown', (e) => onMenuPointerDown(e, host));
});

afterEach(() => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

const li = (id: string): HTMLElement => document.querySelector<HTMLElement>(`li[data-menu-row="${id}"]`)!;
const ptr = (type: string, y: number): PointerEvent => new PointerEvent(type, { clientX: 5, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0, bubbles: true, cancelable: true });

function dragTo(id: string, y: number): void {
  li(id).querySelector('b')!.dispatchEvent(ptr('pointerdown', 10));
  document.dispatchEvent(ptr('pointermove', y));
}

test('while dragging: a ghost copy exists, the old place is collapsed and a gap opens above the row the pointer is over', () => {
  dragTo('a', 40);
  expect(menuDragActive()).toBe(true);
  expect(document.querySelector('[data-drag-ghost]')).not.toBeNull();
  expect(li('a').style.display).toBe('none');
  expect(li('c').getAttribute('data-menu-drop')).toBe('before');
  expect(commit).not.toHaveBeenCalled();
});

test('release commits exactly the previewed order and tears the preview down', () => {
  dragTo('a', 40);
  document.dispatchEvent(ptr('pointerup', 40));
  expect(commit).toHaveBeenCalledWith(['b', 'a', 'c']);
  expect(document.querySelector('[data-drag-ghost]')).toBeNull();
  expect(li('a').style.display).toBe('');
  expect(document.querySelector('[data-menu-drop], [data-menu-lifted]')).toBeNull();
});

test('Escape restores the original order and writes nothing', () => {
  dragTo('a', 40);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(commit).not.toHaveBeenCalled();
  expect(menuDragActive()).toBe(false);
  expect(document.querySelector('[data-drag-ghost]')).toBeNull();
  expect(li('a').style.display).toBe('');
  expect(document.querySelector('[data-menu-drop], [data-menu-lifted]')).toBeNull();
});

test('a cancelled pointer writes nothing either', () => {
  dragTo('b', 80);
  document.dispatchEvent(ptr('pointercancel', 80));
  expect(commit).not.toHaveBeenCalled();
  expect(document.querySelector('[data-drag-ghost]')).toBeNull();
  expect(li('b').style.display).toBe('');
});

/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TabStrip, { type TabItem } from './TabStrip.svelte';

const ITEMS: TabItem[] = [
  { id: 'terminal:a', name: 'a', family: null },
  { id: 'terminal:b', name: 'b', family: null },
  { id: 'terminal:c', name: 'c', family: null },
];

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function draw(props: Partial<Parameters<typeof TabStrip>[1]>): Record<string, HTMLElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabStrip, { target, props: { items: ITEMS, active: 'terminal:a', onSelect: () => {}, ...props } });
  flushSync();
  const boxes: Record<string, HTMLElement> = {};
  for (const button of target.querySelectorAll<HTMLElement>('[data-tab]')) {
    boxes[button.dataset['tab'] ?? ''] = button.closest('.oc-tabwrap') as HTMLElement;
  }
  return boxes;
}

test('the strip names its component, and a press on a tab goes to the drag', () => {
  const onDragStart = vi.fn();
  draw({ group: 'terminal:@primary', onDragStart });
  expect(document.querySelector('[data-tab-group="terminal:@primary"]')).not.toBeNull();
  const button = document.querySelector<HTMLElement>('[data-tab="terminal:b"]');
  button?.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onDragStart).toHaveBeenCalledWith(button, expect.anything(), 'terminal:b');
});

test('the carried tab dims and the mark counts the others', () => {
  const boxes = draw({ group: 'g', dragging: 'terminal:a', dropIndex: 1 });
  expect(boxes['terminal:a']?.classList.contains('tw:opacity-40')).toBe(true);
  expect(boxes['terminal:c']?.dataset['dropMark']).toBe('before');
  expect(boxes['terminal:b']?.dataset['dropMark']).toBeUndefined();
});

test('an index past the last tab marks the end', () => {
  const boxes = draw({ group: 'g', dragging: 'terminal:x', dropIndex: 3 });
  expect(boxes['terminal:c']?.dataset['dropMark']).toBe('after');
});

test('no drop aimed here, no mark', () => {
  const boxes = draw({ group: 'g', dragging: 'terminal:a', dropIndex: null });
  expect(Object.values(boxes).some((box) => box.dataset['dropMark'])).toBe(false);
});

test('the workflow mark sits right of the title only while a workflow runs (#1153)', () => {
  draw({ items: [{ ...ITEMS[0]!, workflow: true }, ITEMS[1]!] });
  const on = document.querySelector('[data-tab="terminal:a"]')!;
  const mark = on.querySelector('.oc-tab-workflow');
  expect(mark?.previousElementSibling?.classList.contains('oc-tab-name')).toBe(true);
  expect(mark?.getAttribute('aria-label')).toBe('running a workflow');
  expect(document.querySelector('[data-tab="terminal:b"] .oc-tab-workflow')).toBeNull();
});

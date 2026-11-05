/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createDragGhost } from './ghost';

afterEach(() => document.body.replaceChildren());

function row(): HTMLElement {
  document.body.innerHTML = '<ul><li id="r1" data-menu-row="a" class="line"><button id="k" tabindex="0" data-rail-key="a">icon</button></li></ul>';
  return document.querySelector('li')!;
}

test('copies the row beside it with identity stripped, hidden from assistive tech and from the pointer', () => {
  const li = row();
  const ghost = createDragGhost(li, { grab: { x: 4, y: 6 }, strip: ['data-menu-row', 'data-rail-key'] });
  const copy = document.querySelector<HTMLElement>('[data-drag-ghost]')!;
  expect(copy.parentElement).toBe(li.parentElement);
  expect(copy.className).toBe('line');
  expect(copy.querySelector('[data-rail-key], [data-menu-row], #k, [tabindex]')).toBeNull();
  expect(copy.hasAttribute('id')).toBe(false);
  expect(copy.getAttribute('aria-hidden')).toBe('true');
  expect(copy.style.pointerEvents).toBe('none');
  expect(copy.style.position).toBe('fixed');
  expect(document.querySelectorAll('[data-menu-row]')).toHaveLength(1);
  ghost.destroy();
});

test('move follows the pointer by the grip; destroy removes it and is safe twice', () => {
  const li = row();
  const ghost = createDragGhost(li, { grab: { x: 4, y: 6 } });
  ghost.move(104, 206);
  expect(document.querySelector<HTMLElement>('[data-drag-ghost]')!.style.transform).toBe('translate(100px, 200px)');
  ghost.destroy();
  ghost.destroy();
  expect(document.querySelector('[data-drag-ghost]')).toBeNull();
});

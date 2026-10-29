/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { GHOST_GUTTER, GHOST_MAX_HEIGHT, startGhost } from './task-manager-ghost';

afterEach(() => {
  document.body.innerHTML = '';
});

function press(): { row: HTMLElement; event: PointerEvent } {
  const row = document.createElement('li');
  row.setAttribute('data-huddle-item', '3');
  row.innerHTML = '<span>title</span><ul data-huddle-infos="3"><li>an info post, long</li></ul>';
  document.body.appendChild(row);
  row.getBoundingClientRect = () => ({ left: 10, top: 100, width: 280, height: 174, right: 290, bottom: 274, x: 10, y: 100, toJSON: () => ({}) });
  return { row, event: { clientX: 22, clientY: 114 } as PointerEvent };
}

describe('the drag ghost', () => {
  it('shows the title strip only, so a tall row cannot cover the landing line', () => {
    const { row, event } = press();
    startGhost(row, event);
    const ghost = document.querySelector<HTMLElement>('[data-task-manager-ghost]') as HTMLElement;
    expect(ghost.style.maxHeight).toBe(`${GHOST_MAX_HEIGHT}px`);
    expect(ghost.style.overflow).toBe('hidden');
    expect(GHOST_MAX_HEIGHT).toBeLessThanOrEqual(40);
  });

  it('starts right of the row, leaving the left gutter (the line marker) uncovered, and keeps the grab offset', () => {
    const { row, event } = press();
    const ghost = startGhost(row, event);
    const el = document.querySelector<HTMLElement>('[data-task-manager-ghost]') as HTMLElement;
    expect(el.style.width).toBe(`${280 - GHOST_GUTTER}px`);
    expect(el.style.transform).toBe(`translate(${22 - 12 + GHOST_GUTTER}px, ${114 - 14}px)`);
    ghost.move(60, 200);
    expect(el.style.transform).toBe(`translate(${60 - 12 + GHOST_GUTTER}px, ${200 - 14}px)`);
    ghost.destroy();
    expect(document.querySelector('[data-task-manager-ghost]')).toBeNull();
  });
});

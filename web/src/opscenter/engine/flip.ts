
import { reducedMotion } from './viewport.svelte';

const DURATION = 220;

const EASING = 'cubic-bezier(.2,.8,.2,1)';

export type CellRects = Map<string, DOMRect>;

function cellElements(): Map<string, HTMLElement> {
  const found = new Map<string, HTMLElement>();
  if (typeof document === 'undefined') return found;
  for (const node of document.querySelectorAll<HTMLElement>('.oc-cellslot[data-slot]')) {
    const id = node.dataset['slot'];
    if (id) found.set(id, node);
  }
  return found;
}

export function measureCells(ids?: readonly string[]): CellRects {
  const rects: CellRects = new Map();
  const elements = cellElements();
  const wanted = ids ?? [...elements.keys()];
  for (const id of wanted) {
    const element = elements.get(id);
    if (element) rects.set(id, element.getBoundingClientRect());
  }
  return rects;
}

export function flipCells(before: CellRects, scrolledBy = 0): void {
  if (reducedMotion()) return;
  const elements = cellElements();
  const moves: { element: HTMLElement; from: DOMRect; to: DOMRect }[] = [];
  for (const [id, element] of elements) {
    const held = before.get(id);
    if (!held || held.width <= 0 || held.height <= 0) continue;
    const from = scrolledBy
      ? new DOMRect(held.x, held.y - scrolledBy, held.width, held.height)
      : held;
    const to = element.getBoundingClientRect();
    if (to.width <= 0 || to.height <= 0) continue;
    if (Math.abs(from.x - to.x) < 1 && Math.abs(from.y - to.y) < 1 && Math.abs(from.width - to.width) < 1 && Math.abs(from.height - to.height) < 1) continue;
    moves.push({ element, from, to });
  }
  for (const move of moves) {
    for (const running of move.element.getAnimations()) running.cancel();
    const dx = move.from.x - move.to.x;
    const dy = move.from.y - move.to.y;
    const sx = move.from.width / move.to.width;
    const sy = move.from.height / move.to.height;
    move.element.animate(
      [
        { transformOrigin: 'top left', transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
        { transformOrigin: 'top left', transform: 'translate(0px, 0px) scale(1, 1)' },
      ],
      { duration: DURATION, easing: EASING, composite: 'replace' },
    );
  }
}

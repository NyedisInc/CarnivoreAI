import { followGrip } from './task-manager-drag';
import { startGhost } from './task-manager-ghost';

export interface AreaHit {
  id: number | null;
}

export function areaTargetAt(root: HTMLElement | null, x: number, y: number): AreaHit | null {
  if (!root) return null;
  for (const el of root.querySelectorAll<HTMLElement>('[data-task-manager-area-drop]')) {
    const r = el.getBoundingClientRect();
    if (y >= r.top && y < r.bottom && x >= r.left && x < r.right) {
      return { id: el.dataset.taskManagerAreaDrop === 'none' ? null : Number(el.dataset.taskManagerAreaDrop) };
    }
  }
  return null;
}

export interface DragHooks {
  onMove: (y: number, x: number, area: AreaHit | null) => void;
  onEnd: (dropped: boolean, area: AreaHit | null) => void;
}

export function beginRowDrag(event: PointerEvent, root: HTMLElement | null, hooks: DragHooks): void {
  const grip = event.currentTarget as HTMLElement | null;
  const ghost = startGhost(grip?.closest<HTMLElement>('[data-huddle-item]') ?? null, event);
  let area: AreaHit | null = null;
  followGrip(event, (y, x) => {
    ghost.move(x, y);
    area = areaTargetAt(root, x, y);
    hooks.onMove(y, x, area);
  }, (dropped) => {
    ghost.destroy();
    const at = area;
    area = null;
    hooks.onEnd(dropped, at);
  });
}


export interface Ghost {
  move: (x: number, y: number) => void;
  destroy: () => void;
}

const GHOST_Z = 2147483000;

export const GHOST_MAX_HEIGHT = 36;

export const GHOST_GUTTER = 20;

const ROW_ATTRS = ['data-huddle-item', 'data-task-manager-grip', 'id', 'aria-describedby', 'aria-labelledby'];

export function startGhost(row: HTMLElement | null, event: PointerEvent): Ghost {
  if (!row) return { move: () => undefined, destroy: () => undefined };
  const box = row.getBoundingClientRect();
  const offsetX = event.clientX - box.left;
  const offsetY = event.clientY - box.top;
  const copy = row.cloneNode(true) as HTMLElement;
  for (const el of [copy, ...copy.querySelectorAll<HTMLElement>('*')]) for (const name of ROW_ATTRS) el.removeAttribute(name);
  copy.setAttribute('data-task-manager-ghost', '');
  copy.setAttribute('aria-hidden', 'true');
  copy.classList.add('tkm--lifted');
  copy.classList.remove('tkm--placeholder');
  Object.assign(copy.style, {
    position: 'fixed', left: '0', top: '0', margin: '0', width: `${box.width - GHOST_GUTTER}px`, maxHeight: `${GHOST_MAX_HEIGHT}px`, overflow: 'hidden', boxSizing: 'border-box',
    pointerEvents: 'none', zIndex: String(GHOST_Z), listStyle: 'none', opacity: '0.94',
  });
  document.body.appendChild(copy);
  const move = (x: number, y: number): void => {
    copy.style.transform = `translate(${x - offsetX + GHOST_GUTTER}px, ${y - offsetY}px)`;
  };
  move(event.clientX, event.clientY);
  return { move, destroy: () => copy.remove() };
}

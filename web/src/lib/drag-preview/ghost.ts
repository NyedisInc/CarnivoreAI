
const IDENTITY_ATTRS: readonly string[] = ['id', 'tabindex', 'name', 'for'];

export const GHOST_CHROME = [
  'box-sizing:border-box', 'border-radius:var(--oc-radius-sm)', 'background:var(--oc-ground-chrome)',
  'box-shadow:inset 0 0 0 var(--oc-border) var(--oc-line-panel)',
].join(';');

const GHOST_STYLE = [
  'position:fixed', 'left:0', 'top:0', 'margin:0', 'pointer-events:none', 'z-index:var(--oc-z-modal)', GHOST_CHROME, 'will-change:transform', 'transition:none',
].join(';');

export interface GhostOptions {
  grab: { x: number; y: number };
  mount?: HTMLElement;
  strip?: readonly string[];
}

export interface DragGhost {
  move(clientX: number, clientY: number): void;
  destroy(): void;
}

function scrub(root: HTMLElement, names: readonly string[]): void {
  for (const el of [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))]) {
    for (const name of names) el.removeAttribute(name);
  }
}

export function createDragGhost(source: HTMLElement, options: GhostOptions): DragGhost {
  const box = source.getBoundingClientRect();
  const copy = source.cloneNode(true) as HTMLElement;
  scrub(copy, [...IDENTITY_ATTRS, ...(options.strip ?? [])]);
  copy.setAttribute('aria-hidden', 'true');
  copy.setAttribute('inert', '');
  copy.setAttribute('data-drag-ghost', '');
  copy.style.cssText = `${GHOST_STYLE};width:${box.width}px;height:${box.height}px`;
  (options.mount ?? source.parentElement ?? document.body).appendChild(copy);
  const home = copy.getBoundingClientRect();
  const move = (clientX: number, clientY: number): void => {
    copy.style.transform = `translate(${clientX - options.grab.x - home.left}px, ${clientY - options.grab.y - home.top}px)`;
  };
  move(box.left + options.grab.x, box.top + options.grab.y);
  return { move, destroy: () => copy.remove() };
}

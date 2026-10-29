import { placeMenu, type Placement } from '../drawer-tabs/add-component-menu';

export function placeUnderAnchor(anchor: HTMLElement | null, panel: HTMLElement | null): Placement | null {
  if (typeof window === 'undefined' || !panel) return null;
  const r = anchor?.getBoundingClientRect();
  const opener = r
    ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom }
    : { left: 0, top: 0, right: 0, bottom: 0 };
  return placeMenu(
    opener,
    null,
    { width: panel.offsetWidth, height: panel.offsetHeight },
    { width: window.innerWidth, height: window.innerHeight },
  );
}

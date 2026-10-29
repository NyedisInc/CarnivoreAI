
export type OverflowKind = 'scroll' | 'clip' | null;

export function isDrawn(el: Element, hidesClipPath = false): boolean {
  const box = el.getBoundingClientRect();
  if (box.width <= 1 || box.height <= 1) return false;
  const html = el as HTMLElement;
  if (typeof html.checkVisibility === 'function' && !html.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
  const style = getComputedStyle(el);
  if (style.clip && style.clip !== 'auto') return false;
  return !(hidesClipPath && style.clipPath && style.clipPath !== 'none' && style.position === 'absolute');
}

export function overflowOf(el: Element, axis: 'x' | 'y'): OverflowKind {
  const value = getComputedStyle(el)[axis === 'x' ? 'overflowX' : 'overflowY'];
  if (value === 'auto' || value === 'scroll') return 'scroll';
  if (value === 'hidden' || value === 'clip') return 'clip';
  return null;
}

const px = (value: string): number => parseFloat(value) || 0;

export function innerBox(el: Element): DOMRect {
  const box = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  const l = px(s.borderLeftWidth);
  const t = px(s.borderTopWidth);
  const r = px(s.borderRightWidth);
  const b = px(s.borderBottomWidth);
  return new DOMRect(box.left + l, box.top + t, Math.max(0, box.width - l - r), Math.max(0, box.height - t - b));
}

export function innerY(el: Element): { top: number; bottom: number } {
  const box = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return { top: box.top + px(s.borderTopWidth), bottom: box.bottom - px(s.borderBottomWidth) };
}

export function innerX(el: Element): { left: number; right: number } {
  const box = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return { left: box.left + px(s.borderLeftWidth), right: box.right - px(s.borderRightWidth) };
}

export function shared(a: DOMRect, b: DOMRect): { x: number; y: number } {
  return {
    x: Math.min(a.right, b.right) - Math.max(a.left, b.left),
    y: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
  };
}

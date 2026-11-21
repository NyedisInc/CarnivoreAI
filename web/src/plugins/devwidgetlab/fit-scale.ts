
export const PHONE_MAX_PX = 560;

export function scaleFor(room: number, frame: number): number {
  if (room <= 0 || frame <= 0 || room >= frame) return 1;
  return Math.max(room / frame, 0.2);
}

export function watchWidth(node: HTMLElement, report: (width: number) => void): () => void {
  report(node.clientWidth);
  if (typeof ResizeObserver === 'undefined') return () => undefined;
  const watch = new ResizeObserver(() => report(node.clientWidth));
  watch.observe(node);
  return () => watch.disconnect();
}

export const PAGE_GUTTER_PX = 26;

/* the phone layout */
export function frameScale(phone: boolean, page: number, frame: number): number {
  return phone ? scaleFor(page - PAGE_GUTTER_PX, frame) : 1;
}

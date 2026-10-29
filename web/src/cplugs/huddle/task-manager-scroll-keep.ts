
export interface RowAnchor {
  el: Element;
  id: string;
  offset: number;
  scrollTop: number;
  index: number;
  order: ReadonlyMap<string, number>;
}

const ROW_ATTR = 'data-huddle-item';

const HEAD_ATTR = 'data-task-manager-level';

const DRIFT_FLOOR_PX = 0.5;

const FALLBACK_ROWS = 5;

export const TOP_SLACK_PX = 4;

const ownScrolls = new WeakMap<HTMLElement, number>();

export function isKeeperScroll(box: HTMLElement): boolean {
  const mark = ownScrolls.get(box);
  if (mark === undefined) return false;
  ownScrolls.delete(box);
  return Math.abs(box.scrollTop - mark) < 1;
}

export function stickyBottomOf(box: HTMLElement): number {
  let line = box.getBoundingClientRect().top;
  const heads = Array.from(box.querySelectorAll<HTMLElement>(`[${HEAD_ATTR}]`), (el) => el.getBoundingClientRect()).sort((x, y) => x.top - y.top);
  for (const rect of heads) {
    if (rect.top <= line + DRIFT_FLOOR_PX && rect.bottom > line) line = rect.bottom;
  }
  return line;
}

export function anchorsOf(box: HTMLElement): RowAnchor[] {
  if (box.scrollTop <= TOP_SLACK_PX) return [];
  const rect = box.getBoundingClientRect();
  const line = stickyBottomOf(box);
  const rows = Array.from(box.querySelectorAll<HTMLElement>(`[${ROW_ATTR}]`));
  const reading = rows.findIndex((el) => el.getBoundingClientRect().bottom > line + DRIFT_FLOOR_PX);
  if (reading < 0 || rows[reading]!.getBoundingClientRect().top >= rect.bottom) return [];
  const order = new Map(rows.map((el, i) => [el.getAttribute(ROW_ATTR) ?? '', i]));
  const found: RowAnchor[] = [];
  for (let i = reading; i >= 0 && found.length <= FALLBACK_ROWS; i -= 1) {
    const el = rows[i] as HTMLElement;
    found.push({ el, id: el.getAttribute(ROW_ATTR) ?? '', offset: el.getBoundingClientRect().top - rect.top, scrollTop: box.scrollTop, index: i, order });
  }
  return found;
}

function crossed(list: readonly HTMLElement[], at: number, was: RowAnchor): boolean {
  const placeOf = (i: number): number | undefined => was.order.get(list[i]?.getAttribute(ROW_ATTR) ?? '');
  for (let i = at - 1; i >= 0; i -= 1) {
    const place = placeOf(i);
    if (place !== undefined) { if (place > was.index) return true; break; }
  }
  for (let i = at + 1; i < list.length; i += 1) {
    const place = placeOf(i);
    if (place !== undefined) return place < was.index;
  }
  return false;
}

export function driftOf(box: HTMLElement, anchors: readonly RowAnchor[], moved: (el: Element) => boolean = () => false): number {
  if (box.scrollTop <= TOP_SLACK_PX) return 0;
  const top = box.getBoundingClientRect().top;
  const list = Array.from(box.querySelectorAll<HTMLElement>(`[${ROW_ATTR}]`));
  for (const was of anchors) {
    if (!box.contains(was.el) || moved(was.el)) continue;
    const i = list.indexOf(was.el as HTMLElement);
    if (i < 0 || crossed(list, i, was)) continue;
    const expected = was.offset - (box.scrollTop - was.scrollTop);
    const drift = was.el.getBoundingClientRect().top - top - expected;
    return Math.abs(drift) < DRIFT_FLOOR_PX ? 0 : drift;
  }
  return 0;
}

function movedBy(records: readonly MutationRecord[]): (el: Element) => boolean {
  const nodes: Node[] = [];
  for (const r of records) {
    if (r.type !== 'childList') continue;
    r.removedNodes.forEach((n) => nodes.push(n));
  }
  return (el) => nodes.some((n) => n === el || n.contains(el));
}

export function createScrollKeeper(box: HTMLElement): () => void {
  let anchors = anchorsOf(box);
  const record = (): void => { anchors = anchorsOf(box); };
  const keep = (moved?: (el: Element) => boolean): void => {
    const drift = anchors.length === 0 ? 0 : driftOf(box, anchors, moved);
    if (drift !== 0) {
      box.scrollTop += drift;
      ownScrolls.set(box, box.scrollTop);
    }
    record();
  };
  const resized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => keep());
  const watchChildren = (): void => {
    if (!resized) return;
    resized.disconnect();
    resized.observe(box);
    for (const child of Array.from(box.children)) resized.observe(child);
  };
  const changed = new MutationObserver((records) => {
    if (records.some((r) => r.type === 'childList' && r.target === box)) watchChildren();
    keep(movedBy(records));
  });
  changed.observe(box, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class', 'style', 'hidden', 'open', 'aria-expanded'] });
  box.addEventListener('scroll', record, { passive: true });
  watchChildren();
  return () => {
    changed.disconnect();
    resized?.disconnect();
    box.removeEventListener('scroll', record);
    ownScrolls.delete(box);
  };
}

/*  hidden  visibility: hidden */
import { wholeRowCount } from './rank-rows';

export interface WholeItemsParams { enabled?: boolean }

export const WHOLE_OFF_ATTR = 'data-whole-off';

function show(item: HTMLElement): void {
  item.removeAttribute(WHOLE_OFF_ATTR);
  item.style.removeProperty('visibility');
}

function mark(node: HTMLElement, enabled: boolean): void {
  const items = [...node.querySelectorAll<HTMLElement>('li')];
  if (!enabled) { for (const item of items) show(item); return; }
  const box = node.getBoundingClientRect();
  const whole = wholeRowCount(box.height, items.map((item) => item.getBoundingClientRect().bottom - box.top));
  items.forEach((item, at) => {
    if (at >= whole) { item.setAttribute(WHOLE_OFF_ATTR, ''); item.style.visibility = 'hidden'; }
    else show(item);
  });
}

export function wholeItems(node: HTMLElement, params: WholeItemsParams = {}): { update(next: WholeItemsParams): void; destroy(): void } {
  let enabled = params.enabled !== false;
  const run = (): void => mark(node, enabled);
  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(run);
  const changes = typeof MutationObserver === 'undefined' ? null : new MutationObserver((records) => {
    if (records.some((record) => record.type === 'childList')) run();
  });
  resize?.observe(node);
  changes?.observe(node, { childList: true, subtree: true });
  run();
  return {
    update(next: WholeItemsParams) { enabled = next.enabled !== false; run(); },
    destroy() { resize?.disconnect(); changes?.disconnect(); },
  };
}

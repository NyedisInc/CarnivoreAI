import { isClipped } from './truncated-tip';

export const REVEAL_ATTR = 'data-cut-off-reveal';
const MAX_DEPTH = 8;

/* overflow:hidden; text-overflow:ellipsis; white-space:nowrap */
export function cutsWithEllipsis(el: Element): boolean {
  const cs = getComputedStyle(el);
  if (cs.textOverflow === 'ellipsis') return true;
  const clamp = cs.getPropertyValue('-webkit-line-clamp') || (cs as unknown as Record<string, string>).webkitLineClamp;
  return !!clamp && clamp !== 'none' && clamp !== '0';
}

export function revealCutOffText(node: Element | null): HTMLElement | null {
  let el: Element | null = node;
  for (let depth = 0; el && depth < MAX_DEPTH; depth += 1, el = el.parentElement) {
    if (!(el instanceof HTMLElement) || el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) continue;
    if (!cutsWithEllipsis(el)) continue;
    const mine = el.hasAttribute(REVEAL_ATTR);
    if (!mine && (el.hasAttribute('data-tooltip') || el.hasAttribute('title') || el.hasAttribute('data-tooltip-title'))) return el;
    const words = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
    if (words && isClipped(el)) {
      el.setAttribute('data-tooltip', words);
      el.setAttribute(REVEAL_ATTR, '');
    } else if (mine) {
      el.removeAttribute('data-tooltip');
      el.removeAttribute(REVEAL_ATTR);
    }
    return el;
  }
  return null;
}

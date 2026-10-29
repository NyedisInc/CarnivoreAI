/*  hidden  */

import catalog from '../../../client/js/i18n/catalog.en.js';

export interface FitFinding {
  rule: 'overflow-x' | 'overflow-y' | 'scrollbar-x' | 'clipped-text' | 'overlap' | 'bad-text' | 'catalog-key' | 'unavailable';
  selector: string;
  px: number;
  detail: string;
}

export const FIT_TOLERANCE_PX = 1;

const BAD_WORDS = /\b(unknown|undefined|null|NaN)\b|\[object Object\]/i;

const NO_CLAMP: Readonly<Record<string, true>> = Object.freeze({ '': true, none: true });

const RAW_ID = /\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b/;

const DOTTED = /\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b/g;

const CATALOG_KEYS: ReadonlySet<string> = new Set(Object.keys(catalog as Record<string, string>));

export function cssPath(el: Element, root: Element): string {
  const parts: string[] = [];
  let at: Element | null = el;
  while (at && at !== root && parts.length < 6) {
    const tag = at.tagName.toLowerCase();
    const classes = [...at.classList].filter((c) => !c.startsWith('svelte-')).slice(0, 2);
    const parent: Element | null = at.parentElement;
    const index = parent ? [...parent.children].indexOf(at) + 1 : 1;
    parts.unshift(`${tag}${classes.map((c) => `.${c}`).join('')}:nth-child(${index})`);
    at = parent;
  }
  return parts.join(' > ');
}

function drawn(el: Element): boolean {
  const box = el.getBoundingClientRect();
  if (box.width <= 1 || box.height <= 1) return false;
  if (typeof (el as HTMLElement).checkVisibility === 'function'
    && !(el as HTMLElement).checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
  const style = getComputedStyle(el);
  if (style.clip && style.clip !== 'auto') return false;
  if (style.clipPath && style.clipPath !== 'none' && style.position === 'absolute') return false;
  return true;
}

function clipsX(el: Element): 'scroll' | 'clip' | null {
  const x = getComputedStyle(el).overflowX;
  if (x === 'auto' || x === 'scroll') return 'scroll';
  if (x === 'hidden' || x === 'clip') return 'clip';
  return null;
}

function clipsY(el: Element): 'scroll' | 'clip' | null {
  const y = getComputedStyle(el).overflowY;
  if (y === 'auto' || y === 'scroll') return 'scroll';
  if (y === 'hidden' || y === 'clip') return 'clip';
  return null;
}

function innerY(el: Element): { top: number; bottom: number } {
  const box = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return {
    top: box.top + (parseFloat(style.borderTopWidth) || 0),
    bottom: box.bottom - (parseFloat(style.borderBottomWidth) || 0),
  };
}

function clipperOfY(el: Element, cell: Element): Element {
  let at = el.parentElement;
  while (at && at !== cell) {
    if (clipsY(at)) return at;
    at = at.parentElement;
  }
  return cell;
}

export const OVERLAP_TOLERANCE_PX = 2;

interface TextRun {
  el: Element;
  box: DOMRect;
}

function textRuns(cell: Element): TextRun[] {
  const runs: TextRun[] = [];
  const walker = cell.ownerDocument.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
  const range = cell.ownerDocument.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!el || !(node.textContent ?? '').trim() || el.closest('svg') || !drawn(el)) continue;
    if (insideMarked(el, cell, 'data-fit-clip')) continue;
    range.selectNodeContents(node);
    const box = visiblePart(range.getBoundingClientRect(), el, cell);
    if (box.width > 1 && box.height > 1) runs.push({ el, box });
  }
  return runs;
}

/*  hidden
 */
function visiblePart(box: DOMRect, el: Element, cell: Element): DOMRect {
  let { left, right, top, bottom } = box;
  for (let at: Element | null = el; at && cell.contains(at); at = at.parentElement) {
    const edge = at.getBoundingClientRect();
    if (clipsX(at)) {
      left = Math.max(left, edge.left);
      right = Math.min(right, edge.right);
    }
    if (clipsY(at)) {
      top = Math.max(top, edge.top);
      bottom = Math.min(bottom, edge.bottom);
    }
    if (at === cell) break;
  }
  return new DOMRect(left, top, Math.max(0, right - left), Math.max(0, bottom - top));
}

function shared(a: DOMRect, b: DOMRect): { x: number; y: number } {
  return {
    x: Math.min(a.right, b.right) - Math.max(a.left, b.left),
    y: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
  };
}

function innerX(el: Element): { left: number; right: number } {
  const box = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return {
    left: box.left + (parseFloat(style.borderLeftWidth) || 0),
    right: box.right - (parseFloat(style.borderRightWidth) || 0),
  };
}

function clipperOf(el: Element, cell: Element): Element {
  let at = el.parentElement;
  while (at && at !== cell) {
    if (clipsX(at)) return at;
    at = at.parentElement;
  }
  return cell;
}

function insideMarked(el: Element, cell: Element, attr: string): boolean {
  const marked = el.parentElement?.closest(`[${attr}]`);
  return Boolean(marked && cell.contains(marked));
}

function ownText(el: Element): string {
  let text = '';
  for (const node of el.childNodes) if (node.nodeType === Node.TEXT_NODE) text += node.textContent ?? '';
  return text.replace(/\s+/g, ' ').trim();
}

export function fitCheck(cell: Element): FitFinding[] {
  const found: FitFinding[] = [];
  const failed = new Map<FitFinding['rule'], Element[]>();
  const add = (el: Element, finding: FitFinding): void => {
    const seen = failed.get(finding.rule) ?? [];
    if (seen.some((one) => one.contains(el))) return;
    seen.push(el);
    failed.set(finding.rule, seen);
    found.push(finding);
  };
  const scrollersSeen = new Set<Element>();

  for (const el of [cell, ...cell.querySelectorAll('*')]) {
    if (!drawn(el)) continue;
    const box = el.getBoundingClientRect();

    if (el !== cell && clipsX(el) === 'scroll' && !el.hasAttribute('data-fit-scroll-x')
      && el.scrollWidth > el.clientWidth + FIT_TOLERANCE_PX && !scrollersSeen.has(el)) {
      scrollersSeen.add(el);
      add(el, { rule: 'scrollbar-x', selector: cssPath(el, cell), px: el.scrollWidth - el.clientWidth,
        detail: `scrolls sideways: content ${el.scrollWidth}px in ${el.clientWidth}px` });
    }
    if (el === cell && clipsX(el) === 'scroll' && el.scrollWidth > el.clientWidth + FIT_TOLERANCE_PX) {
      add(el, { rule: 'scrollbar-x', selector: '(cell)', px: el.scrollWidth - el.clientWidth,
        detail: `the cell's content is ${el.scrollWidth}px wide in ${el.clientWidth}px` });
    }

    if (el !== cell && !insideMarked(el, cell, 'data-fit-clip')) {
      const clipperY = clipperOfY(el, cell);
      if (clipperY === cell || clipsY(clipperY) !== 'scroll') {
        const edge = innerY(clipperY);
        const past = Math.max(box.bottom - edge.bottom, edge.top - box.top);
        if (past > FIT_TOLERANCE_PX) {
          const where = clipperY === cell ? 'the cell' : cssPath(clipperY, cell);
          add(el, { rule: 'overflow-y', selector: cssPath(el, cell), px: Math.round(past),
            detail: `runs ${Math.round(past)}px past the top or bottom of ${where} (${Math.round(box.height)}px tall)` });
        }
      }
    }

    if (el !== cell && !insideMarked(el, cell, 'data-fit-scroll-x') && !insideMarked(el, cell, 'data-fit-clip')) {
      const clipper = clipperOf(el, cell);
      const scrolls = clipper !== cell && clipsX(clipper) === 'scroll';
      if (!scrolls) {
        const edge = innerX(clipper);
        const past = Math.max(box.right - edge.right, edge.left - box.left);
        if (past > FIT_TOLERANCE_PX) {
          const where = clipper === cell ? 'the cell' : cssPath(clipper, cell);
          add(el, { rule: 'overflow-x', selector: cssPath(el, cell), px: Math.round(past),
            detail: `runs ${Math.round(past)}px past ${where} (${Math.round(box.width)}px wide)` });
        }
      }
    }

    const text = ownText(el);
    if (!text) continue;
    const style = getComputedStyle(el);
    if ((style.overflowX === 'hidden' || style.overflowX === 'clip') && style.textOverflow !== 'ellipsis'
      && el.scrollWidth > el.clientWidth + FIT_TOLERANCE_PX && !insideMarked(el, cell, 'data-fit-clip')) {
      add(el, { rule: 'clipped-text', selector: cssPath(el, cell), px: el.scrollWidth - el.clientWidth,
        detail: `"${text.slice(0, 60)}" cut off with no ellipsis` });
    }
    if ((style.overflowY === 'hidden' || style.overflowY === 'clip') && style.getPropertyValue('-webkit-line-clamp') in NO_CLAMP
      && el.scrollHeight > el.clientHeight + FIT_TOLERANCE_PX && !insideMarked(el, cell, 'data-fit-clip')) {
      add(el, { rule: 'clipped-text', selector: cssPath(el, cell), px: el.scrollHeight - el.clientHeight,
        detail: `"${text.slice(0, 60)}" cut off ${el.scrollHeight - el.clientHeight}px vertically (mid-glyph) with no line clamp` });
    }
    const bad = BAD_WORDS.exec(text) ?? RAW_ID.exec(text);
    if (bad) {
      add(el, { rule: 'bad-text', selector: cssPath(el, cell), px: 0, detail: `shows "${bad[0]}" in "${text.slice(0, 60)}"` });
    }
    for (const token of text.match(DOTTED) ?? []) {
      if (CATALOG_KEYS.has(token)) {
        add(el, { rule: 'catalog-key', selector: cssPath(el, cell), px: 0, detail: `shows the catalog key "${token}"` });
        break;
      }
    }
  }
  const runs = textRuns(cell);
  for (let i = 0; i < runs.length; i += 1) {
    for (let j = i + 1; j < runs.length; j += 1) {
      const a = runs[i]!;
      const b = runs[j]!;
      if (a.el === b.el) continue;
      const both = shared(a.box, b.box);
      if (both.x > OVERLAP_TOLERANCE_PX && both.y > OVERLAP_TOLERANCE_PX) {
        add(b.el, { rule: 'overlap', selector: cssPath(b.el, cell), px: Math.round(Math.min(both.x, both.y)),
          detail: `"${(b.el.textContent ?? '').trim().slice(0, 40)}" is drawn over "${(a.el.textContent ?? '').trim().slice(0, 40)}" (${cssPath(a.el, cell)})` });
      }
    }
  }
  return found.sort((a, b) => b.px - a.px);
}


export function unavailableFindings(cell: Element, declared: boolean): FitFinding[] {
  if (!declared) return [];
  const plate = cell.querySelector('[data-widget-unavailable]');
  if (!plate) return [];
  return [{ rule: 'unavailable', selector: cssPath(plate, cell), px: 0,
    detail: `draws the not-available plate (${plate.getAttribute('data-widget-refusal') ?? 'misfit'}) at a size it calls out` }];
}

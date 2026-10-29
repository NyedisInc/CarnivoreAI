/* padding */

import { cssPath } from './fit-probe';
import { contrastRatio, effectiveBackground, inheritedOpacity, over, parseColor } from './layout-color';

export type DefectRule = 'overlap' | 'clipped' | 'ellipsis' | 'escape' | 'tiny-text' | 'low-contrast' | 'wrap' | 'no-text';

export interface Defect {
  rule: DefectRule;
  severity: 'fail' | 'warn';
  selector: string;
  px: number;
  detail: string;
}

export interface DefectReport {
  findings: Defect[];
  checked: { texts: number; graphics: number; elements: number };
}

export const OVERLAP_PX = 1.5;
export const EDGE_PX = 1;
/**
 * The smallest readable font size. The design system's smallest type token is
 * `--oc-fs-micro`, 10px (`opscenter/tokens.css`); anything under it is off the
 * type scale, and at 9px a monospace face loses the counters that tell 0 from 8
 * and 1 from l. A quarter pixel of slack absorbs a scaled `calc()`.
 */
export const MIN_FONT_PX = 10;
const FONT_SLACK_PX = 0.25;
export const CONTRAST_LABEL = 3;
export const CONTRAST_BODY = 4.5;

interface TextLine {
  el: Element;
  node: Text;
  full: DOMRect;
  seen: DOMRect;
}

interface Graphic {
  el: Element;
  seen: DOMRect;
}

const GRAPHIC_TAGS: ReadonlySet<string> = new Set(['svg', 'canvas', 'img', 'video']);
const CONTROL_TAGS: ReadonlySet<string> = new Set(['input', 'textarea', 'select', 'button', 'option']);

function isDrawn(el: Element): boolean {
  const box = el.getBoundingClientRect();
  if (box.width <= 1 || box.height <= 1) return false;
  const html = el as HTMLElement;
  if (typeof html.checkVisibility === 'function' && !html.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
  const style = getComputedStyle(el);
  return !(style.clip && style.clip !== 'auto');
}

function overflowOf(el: Element, axis: 'x' | 'y'): 'scroll' | 'clip' | null {
  const value = getComputedStyle(el)[axis === 'x' ? 'overflowX' : 'overflowY'];
  if (value === 'auto' || value === 'scroll') return 'scroll';
  if (value === 'hidden' || value === 'clip') return 'clip';
  return null;
}

function innerBox(el: Element): DOMRect {
  const box = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  const l = parseFloat(s.borderLeftWidth) || 0;
  const t = parseFloat(s.borderTopWidth) || 0;
  const r = parseFloat(s.borderRightWidth) || 0;
  const b = parseFloat(s.borderBottomWidth) || 0;
  return new DOMRect(box.left + l, box.top + t, Math.max(0, box.width - l - r), Math.max(0, box.height - t - b));
}

function intersect(a: DOMRect, b: DOMRect): DOMRect {
  const left = Math.max(a.left, b.left);
  const top = Math.max(a.top, b.top);
  return new DOMRect(left, top, Math.max(0, Math.min(a.right, b.right) - left), Math.max(0, Math.min(a.bottom, b.bottom) - top));
}

function shared(a: DOMRect, b: DOMRect): { x: number; y: number } {
  return { x: Math.min(a.right, b.right) - Math.max(a.left, b.left), y: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) };
}

function clippers(el: Element, cell: Element, withCell: boolean): Element[] {
  const out: Element[] = [];
  for (let at = el.parentElement; at && cell.contains(at); at = at.parentElement) {
    if (at === cell) {
      if (withCell) out.push(at);
      break;
    }
    if (overflowOf(at, 'x') || overflowOf(at, 'y')) out.push(at);
  }
  return out;
}

function seenPart(rect: DOMRect, chain: readonly Element[]): DOMRect {
  let seen = rect;
  for (const at of chain) {
    const edge = innerBox(at);
    const x = overflowOf(at, 'x') || at.matches('[data-harness-cell]');
    const y = overflowOf(at, 'y') || at.matches('[data-harness-cell]');
    seen = intersect(seen, new DOMRect(x ? edge.left : -1e6, y ? edge.top : -1e6, x ? edge.width : 2e6, y ? edge.height : 2e6));
  }
  return seen;
}

function marked(el: Element, cell: Element, attr: string): boolean {
  const hit = el.closest(`[${attr}]`);
  return Boolean(hit && cell.contains(hit));
}

function emBox(rect: DOMRect, el: Element): DOMRect {
  const em = parseFloat(getComputedStyle(el).fontSize) || rect.height;
  if (rect.height <= em) return rect;
  return new DOMRect(rect.left, rect.top + (rect.height - em) / 2, rect.width, em);
}

function quote(el: Element): string {
  return `"${(el.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 40)}"`;
}

function textLines(cell: Element): TextLine[] {
  const lines: TextLine[] = [];
  const walker = cell.ownerDocument.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
  const range = cell.ownerDocument.createRange();
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const el = node.parentElement;
    if (!el || !(node.textContent ?? '').trim() || !isDrawn(el) || marked(el, cell, 'data-fit-clip')) continue;
    range.selectNodeContents(node);
    //  hidden 
    const chain = overflowOf(el, 'x') || overflowOf(el, 'y') ? [el, ...clippers(el, cell, true)] : clippers(el, cell, true);
    for (const full of range.getClientRects()) {
      if (full.width < 1 || full.height < 1) continue;
      lines.push({ el, node, full, seen: seenPart(full, chain) });
    }
  }
  return lines;
}

function paintedLeaf(el: Element): boolean {
  if (el.childElementCount > 0 || (el.textContent ?? '').trim()) return false;
  const style = getComputedStyle(el);
  return parseColor(style.backgroundColor).a > 0 || (style.backgroundImage !== 'none' && style.backgroundImage !== '');
}

function graphics(cell: Element): Graphic[] {
  const out: Graphic[] = [];
  for (const el of cell.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase();
    if (CONTROL_TAGS.has(tag) || marked(el, cell, 'data-fit-backdrop') || marked(el, cell, 'data-fit-clip')) continue;
    if (tag !== 'svg' && el.closest('svg')) continue;
    if (!(GRAPHIC_TAGS.has(tag) || paintedLeaf(el)) || !isDrawn(el)) continue;
    const seen = seenPart(el.getBoundingClientRect(), clippers(el, cell, true));
    if (seen.width > EDGE_PX * 2 && seen.height > EDGE_PX * 2) out.push({ el, seen });
  }
  return out;
}

function overlapRule(lines: readonly TextLine[], art: readonly Graphic[], cell: Element, add: (el: Element, d: Defect) => void): void {
  const cores = lines.map((line) => ({ line, core: intersect(emBox(line.full, line.el), line.seen) }));
  const live = cores.filter((one) => one.core.width > 0 && one.core.height > 0);
  for (let i = 0; i < live.length; i += 1) {
    const a = live[i]!;
    for (let j = i + 1; j < live.length; j += 1) {
      const b = live[j]!;
      if (a.line.node === b.line.node) continue;
      const both = shared(a.core, b.core);
      if (both.x > OVERLAP_PX && both.y > OVERLAP_PX) {
        add(b.line.el, { rule: 'overlap', severity: 'fail', selector: cssPath(b.line.el, cell), px: Math.round(Math.min(both.x, both.y)),
          detail: `text ${quote(b.line.el)} is drawn over text ${quote(a.line.el)} (${cssPath(a.line.el, cell)})` });
      }
    }
    for (const g of art) {
      if (g.el.contains(a.line.el)) continue;
      const both = shared(a.core, g.seen);
      if (both.x > OVERLAP_PX && both.y > OVERLAP_PX) {
        add(a.line.el, { rule: 'overlap', severity: 'fail', selector: cssPath(a.line.el, cell), px: Math.round(Math.min(both.x, both.y)),
          detail: `text ${quote(a.line.el)} is drawn over a graphic <${g.el.tagName.toLowerCase()}> (${cssPath(g.el, cell)})` });
      }
    }
  }
}

function cutter(line: TextLine, cell: Element): Element | null {
  for (const at of [line.el, ...clippers(line.el, cell, true)]) {
    if (at === line.el && !overflowOf(at, 'x') && !overflowOf(at, 'y')) continue;
    const edge = innerBox(at);
    if (line.full.left < edge.left - EDGE_PX || line.full.right > edge.right + EDGE_PX
      || line.full.top < edge.top - EDGE_PX || line.full.bottom > edge.bottom + EDGE_PX) return at;
  }
  return null;
}

function endsInEllipsis(line: TextLine, by: Element): boolean {
  for (let at: Element | null = line.el; at; at = at.parentElement) {
    const style = getComputedStyle(at);
    if (style.textOverflow === 'ellipsis' || !['', 'none'].includes(style.getPropertyValue('-webkit-line-clamp'))) return true;
    if (at === by) break;
  }
  return false;
}

function clippedRule(lines: readonly TextLine[], cell: Element, add: (el: Element, d: Defect) => void): void {
  for (const line of lines) {
    const cutX = line.full.width - line.seen.width;
    const cutY = line.full.height - line.seen.height;
    if (Math.max(cutX, cutY) <= EDGE_PX || marked(line.el, cell, 'data-fit-truncate')) continue;
    const by = cutter(line, cell);
    if (!by || (by !== cell && overflowOf(by, cutX > cutY ? 'x' : 'y') === 'scroll')) continue;
    const intended = endsInEllipsis(line, by);
    add(line.el, { rule: intended ? 'ellipsis' : 'clipped', severity: intended ? 'warn' : 'fail', selector: cssPath(line.el, cell),
      px: Math.round(Math.max(cutX, cutY)),
      detail: `${quote(line.el)} cut ${Math.round(Math.max(cutX, cutY))}px ${cutX > cutY ? 'sideways' : 'vertically'} by ${by === cell ? 'the cell' : cssPath(by, cell)}${intended ? ' (ends in an ellipsis)' : ''}` });
  }
  for (const el of new Set(lines.map((line) => line.el))) {
    if (marked(el, cell, 'data-fit-truncate')) continue;
    const style = getComputedStyle(el);
    const overX = overflowOf(el, 'x') === 'clip' && el.scrollWidth > el.clientWidth + EDGE_PX;
    const overY = overflowOf(el, 'y') === 'clip' && el.scrollHeight > el.clientHeight + EDGE_PX;
    if (!overX && !overY) continue;
    const intended = overX ? style.textOverflow === 'ellipsis' : !['', 'none'].includes(style.getPropertyValue('-webkit-line-clamp'));
    const px = overX ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
    add(el, { rule: intended ? 'ellipsis' : 'clipped', severity: intended ? 'warn' : 'fail', selector: cssPath(el, cell), px,
      detail: `${quote(el)} overflows its own box by ${px}px ${overX ? 'sideways' : 'vertically'}${intended ? ' (ends in an ellipsis)' : ''}` });
  }
}

function escapeRule(cell: Element, add: (el: Element, d: Defect) => void): number {
  const edge = innerBox(cell);
  let measured = 0;
  for (const el of cell.querySelectorAll('*')) {
    if (!isDrawn(el) || marked(el, cell, 'data-fit-clip')) continue;
    measured += 1;
    const chain = clippers(el, cell, false);
    if (chain.some((at) => overflowOf(at, 'x') === 'scroll' || overflowOf(at, 'y') === 'scroll')) continue;
    const seen = seenPart(el.getBoundingClientRect(), chain);
    if (seen.width <= 0 || seen.height <= 0) continue;
    const past = Math.max(edge.left - seen.left, seen.right - edge.right, edge.top - seen.top, seen.bottom - edge.bottom);
    if (past > EDGE_PX) {
      add(el, { rule: 'escape', severity: 'fail', selector: cssPath(el, cell), px: Math.round(past),
        detail: `<${el.tagName.toLowerCase()}> ${quote(el)} is drawn ${Math.round(past)}px past the cell's edge` });
    }
  }
  return measured;
}

function isLabel(style: CSSStyleDeclaration): boolean {
  const size = parseFloat(style.fontSize) || 0;
  const bold = (parseInt(style.fontWeight, 10) || 400) >= 700;
  return style.textTransform === 'uppercase' || size >= 24 || (bold && size >= 18.66);
}

function typeRules(lines: readonly TextLine[], cell: Element, add: (el: Element, d: Defect) => void): void {
  const byEl = new Map<Element, TextLine[]>();
  for (const line of lines) byEl.set(line.el, [...(byEl.get(line.el) ?? []), line]);
  for (const [el, own] of byEl) {
    if (own.every((line) => line.seen.width <= 0 || line.seen.height <= 0)) continue;
    const style = getComputedStyle(el);
    const size = parseFloat(style.fontSize) || 0;
    if (size < MIN_FONT_PX - FONT_SLACK_PX) {
      add(el, { rule: 'tiny-text', severity: 'fail', selector: cssPath(el, cell), px: size,
        detail: `${quote(el)} is set at ${size}px, under the ${MIN_FONT_PX}px floor` });
    }
    if (!el.closest('svg')) {
      const ground = effectiveBackground(el);
      const ink = parseColor(style.color);
      const shown = over({ ...ink, a: ink.a * inheritedOpacity(el) }, ground.color);
      const ratio = contrastRatio(shown, ground.color);
      const floor = isLabel(style) ? CONTRAST_LABEL : CONTRAST_BODY;
      if (ratio < floor) {
        const quiet = el.closest('[aria-hidden="true"], [aria-disabled="true"], :disabled');
        add(el, { rule: 'low-contrast', severity: quiet || !ground.certain ? 'warn' : 'fail', selector: cssPath(el, cell), px: Math.round(ratio * 100),
          detail: `${quote(el)} contrast ${ratio.toFixed(2)}:1, under ${floor}:1${quiet ? ' (decorative or disabled)' : ''}${ground.certain ? '' : ' (background is not one color)'}` });
      }
    }
    if (el.closest('[data-fit-single-line]')) {
      const tops = new Set(own.map((line) => Math.round(line.full.top / Math.max(1, size / 2))));
      if (tops.size > 1) {
        add(el, { rule: 'wrap', severity: 'fail', selector: cssPath(el, cell), px: tops.size,
          detail: `${quote(el)} wraps to ${tops.size} lines where it is declared one line` });
      }
    }
  }
}

export function layoutDefects(cell: Element): DefectReport {
  const findings: Defect[] = [];
  const seen = new Map<DefectRule, Element[]>();
  const add = (el: Element, defect: Defect): void => {
    const done = seen.get(defect.rule) ?? [];
    if (done.some((one) => one === el || (defect.rule === 'escape' && one.contains(el)))) return;
    done.push(el);
    seen.set(defect.rule, done);
    findings.push(defect);
  };
  const lines = textLines(cell);
  const art = graphics(cell);
  overlapRule(lines, art, cell, add);
  clippedRule(lines, cell, add);
  const elements = escapeRule(cell, add);
  typeRules(lines, cell, add);
  const texts = lines.filter((line) => line.seen.width > 0 && line.seen.height > 0).length;
  if (texts === 0) {
    findings.push({ rule: 'no-text', severity: 'fail', selector: '(cell)', px: 0,
      detail: 'no visible text in the cell: the text rules looked at nothing' });
  }
  findings.sort((a, b) => (a.severity === b.severity ? b.px - a.px : a.severity === 'fail' ? -1 : 1));
  return { findings, checked: { texts, graphics: art.length, elements } };
}


import type { LayoutPage, SlotId } from '../types';
import type { LayoutNode, LayoutV7, SizeClass, SplitNode } from './types';
import { SIZE_CLASSES } from './types';

export const TERMINAL_PREFIX = 'terminal:';

export interface Rect {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export function leavesOf(root: LayoutNode): SlotId[] {
  const out: SlotId[] = [];
  const visit = (node: LayoutNode): void => {
    if (node.t === 'leaf') {
      out.push(node.id);
      return;
    }
    for (const child of node.children) visit(child);
  };
  visit(root);
  return out;
}

export function splitsOf(root: LayoutNode): SplitNode[] {
  const out: SplitNode[] = [];
  const visit = (node: LayoutNode): void => {
    if (node.t === 'leaf') return;
    out.push(node);
    for (const child of node.children) visit(child);
  };
  visit(root);
  return out;
}

export function normalizeShares(sizes: readonly number[]): number[] {
  const total = sizes.reduce((sum, one) => (Number.isFinite(one) && one > 0 ? sum + one : sum), 0);
  if (total <= 0) return sizes.map(() => 1 / sizes.length);
  return sizes.map((one) => (Number.isFinite(one) && one > 0 ? one / total : 0));
}

function isPixelRoot(node: LayoutNode, isRoot: boolean, page: LayoutPage): boolean {
  return isRoot && page === 'home' && node.t === 'split' && node.unit === 'px' && node.dir === 'v';
}

export function canonicalize(root: LayoutNode, page: LayoutPage): LayoutNode {
  const visit = (node: LayoutNode, isRoot: boolean): LayoutNode => {
    if (node.t === 'leaf') return node;
    const children: LayoutNode[] = [];
    const sizes: number[] = [];
    let changed = false;
    node.children.forEach((child, at) => {
      const made = visit(child, false);
      if (made !== child) changed = true;
      const size = node.sizes[at] ?? 0;
      if (made.t === 'split' && made.dir === node.dir) {
        changed = true;
        const inner = normalizeShares(made.sizes);
        made.children.forEach((grand, j) => {
          children.push(grand);
          sizes.push((inner[j] ?? 0) * size);
        });
        return;
      }
      children.push(made);
      sizes.push(size);
    });
    if (children.length === 1 && !isPixelRoot(node, isRoot, page)) return children[0] as LayoutNode;
    const scaled = node.unit === 'fr' ? normalizeShares(sizes) : sizes;
    if (!changed && scaled.every((one, at) => Math.abs(one - (node.sizes[at] ?? Number.NaN)) < 1e-12)) return node;
    return { ...node, sizes: scaled, children };
  };
  return visit(root, true);
}

export function removeLeaf(root: LayoutNode, id: SlotId, page: LayoutPage): LayoutNode | null {
  let found = false;
  const visit = (node: LayoutNode): LayoutNode | null => {
    if (node.t === 'leaf') {
      if (node.id !== id) return node;
      found = true;
      return null;
    }
    const children: LayoutNode[] = [];
    const sizes: number[] = [];
    node.children.forEach((child, at) => {
      const kept = visit(child);
      if (!kept) return;
      children.push(kept);
      sizes.push(node.sizes[at] ?? 0);
    });
    if (children.length === 0) return null;
    return { ...node, children, sizes: node.unit === 'fr' ? normalizeShares(sizes) : sizes };
  };
  const out = visit(root);
  if (!found) return root;
  return out ? canonicalize(out, page) : null;
}

export function terminalSlotsOf(layout: LayoutV7): SlotId[] {
  const out: SlotId[] = [];
  for (const id of leavesOf(layout.variants.wide.root)) {
    if (id.startsWith(TERMINAL_PREFIX) && !out.includes(id)) out.push(id);
  }
  return out;
}

export function withoutSlot(layout: LayoutV7, slot: SlotId, page: LayoutPage): LayoutV7 | null {
  const variants = { ...layout.variants };
  for (const size of SIZE_CLASSES as readonly SizeClass[]) {
    const root = removeLeaf(layout.variants[size].root, slot, page);
    if (!root) return null;
    variants[size] = { root };
  }
  return {
    ...layout,
    variants,
    hidden: layout.hidden.filter((one) => one !== slot),
    collapsed: layout.collapsed.filter((one) => one !== slot),
    ...(layout.headerOff ? { headerOff: layout.headerOff.filter((one) => one !== slot) } : {}),
  };
}

export function rectsOf(root: LayoutNode): Map<SlotId, Rect> {
  const out = new Map<SlotId, Rect>();
  const height = root.t === 'split' && root.unit === 'px' ? root.sizes.reduce((sum, one) => sum + one, 0) : 1;
  const visit = (node: LayoutNode, box: Rect): void => {
    if (node.t === 'leaf') {
      out.set(node.id, box);
      return;
    }
    const along = node.dir === 'h' ? box.x1 - box.x0 : box.y1 - box.y0;
    const shares = node.unit === 'px' ? node.sizes : node.sizes.map((one) => one * along);
    let cursor = node.dir === 'h' ? box.x0 : box.y0;
    node.children.forEach((child, at) => {
      const size = shares[at] ?? 0;
      const next = cursor + size;
      visit(child, node.dir === 'h' ? { ...box, x0: cursor, x1: next } : { ...box, y0: cursor, y1: next });
      cursor = next;
    });
  };
  visit(root, { x0: 0, x1: 1, y0: 0, y1: height });
  return out;
}

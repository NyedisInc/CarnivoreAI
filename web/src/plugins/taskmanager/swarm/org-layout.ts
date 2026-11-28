import type { FloorItem } from './floor';
import type { SwarmTree, TreeNode } from './swarm-tree';
import { sizeOf } from './panel-state';

export const GAP_X = 16;
export const GAP_Y = 36;
const LABEL_H = 14;
const FACE_GAP = 4;
const CHAR_W = 6.2;
const LABEL_MAX = 30;
const LABEL_PAD = 8;
export const STACK_ROWS = 6;
const STACK_COLS = 3;
const STACK_INDENT = 14;
const STACK_GAP = 10;
const LEAF_MAX = 24;
const LEAF_GAP = 8;
const FIT_PAD = 16;
export const ZOOM_MIN = 0.4;
export const ZOOM_MAX = 2.5;
export const ZOOM_STEP = 1.2;

export interface OrgNode {
  key: string;
  x: number;
  y: number;
  w: number;
  h: number;
  stacked: boolean;
}

export interface OrgLink {
  from: string;
  to: string;
  d: string;
}

export interface OrgLayout {
  nodes: OrgNode[];
  links: OrgLink[];
  width: number;
  height: number;
}

export interface OrgView {
  x: number;
  y: number;
  k: number;
}

function boxOf(item: FloorItem): { w: number; h: number } {
  const face = sizeOf(item.rank, 'detailed');
  const text = Math.min(item.label.length, LABEL_MAX) * CHAR_W + LABEL_PAD;
  return { w: Math.max(face, text), h: face + FACE_GAP + LABEL_H };
}

function leafBoxOf(item: FloorItem): { w: number; h: number } {
  const face = sizeOf(item.rank, 'detailed');
  return { w: face + LEAF_GAP + Math.min(item.label.length, LEAF_MAX) * CHAR_W + LABEL_PAD, h: face };
}

interface Stack {
  leaves: string[];
  cols: number;
  rows: number;
  colW: number;
  rowH: number;
  w: number;
  h: number;
}

export function layoutOrg(tree: SwarmTree, maxW = Number.POSITIVE_INFINITY): OrgLayout {
  const nodeOf = (key: string): TreeNode => tree.nodes.get(key) as TreeNode;
  const isLeaf = (key: string): boolean => {
    const node = nodeOf(key);
    return node.children.length === 0 && node.parent !== null && node.item.rank === 'task';
  };
  const box = new Map<string, { w: number; h: number }>();
  const span = new Map<string, number>();
  const stacks = new Map<string, Stack>();
  const inner = new Map<string, string[]>();
  const rows = new Map<string, string[][]>();
  const rowW = new Map<string, number[]>();
  const gutter = new Map<string, number>();
  const level = new Map<string, number>();
  const levelH: number[] = [];
  const grow = (lvl: number, h: number): void => { levelH[lvl] = Math.max(levelH[lvl] ?? 0, h); };
  const midOf = (key: string): number => {
    const row = (rows.get(key) as string[][])[0] as string[];
    const sp = gutter.get(key) as number;
    if (!row.length) return 0;
    const lastKid = row[row.length - 1] as string;
    return sp + (centreOf(row[0] as string) + (rowW.get(key) as number[])[0]! - (span.get(lastKid) as number) + centreOf(lastKid)) / 2;
  };
  const centreOf = (key: string): number => {
    const half = (box.get(key) as { w: number }).w / 2;
    return stacks.has(key) && !(inner.get(key) as string[]).length ? half : Math.max(half, midOf(key));
  };
  const pack = (kids: string[], avail: number): { rs: string[][]; ws: number[] } => {
    const rs: string[][] = [[]];
    const ws: number[] = [0];
    for (const c of kids) {
      const r = rs.length - 1;
      const s = span.get(c) as number;
      const filled = (rs[r] as string[]).length > 0;
      if (filled && (ws[r] as number) + GAP_X + s > avail) {
        rs.push([c]);
        ws.push(s);
      } else {
        (rs[r] as string[]).push(c);
        ws[r] = (ws[r] as number) + (filled ? GAP_X : 0) + s;
      }
    }
    return { rs, ws };
  };
  const measure = (key: string): number => {
    const node = nodeOf(key);
    const b = boxOf(node.item);
    box.set(key, b);
    const leaves = node.children.filter(isLeaf);
    const kids = node.children.filter((c) => !isLeaf(c));
    inner.set(key, kids);
    if (leaves.length) {
      for (const c of leaves) box.set(c, leafBoxOf(nodeOf(c).item));
      const cols = Math.min(STACK_COLS, Math.ceil(leaves.length / STACK_ROWS));
      const rowsN = Math.ceil(leaves.length / cols);
      const colW = Math.max(...leaves.map((c) => (box.get(c) as { w: number }).w));
      const rowH = Math.max(...leaves.map((c) => (box.get(c) as { h: number }).h));
      stacks.set(key, { leaves, cols, rows: rowsN, colW, rowH, w: cols * (STACK_INDENT + colW) + (cols - 1) * GAP_X, h: rowsN * rowH + (rowsN - 1) * STACK_GAP });
    }
    for (const c of kids) measure(c);
    const st = stacks.get(key);
    let packed = pack(kids, maxW);
    let sp = 0;
    if (packed.rs.length > 1) {
      sp = GAP_X;
      packed = pack(kids, maxW - sp);
    }
    rows.set(key, packed.rs);
    rowW.set(key, packed.ws);
    gutter.set(key, sp);
    const w = st && !kids.length ? b.w / 2 + Math.max(b.w / 2, st.w) : centreOf(key) + Math.max(b.w / 2, st ? st.w : 0, sp + Math.max(...packed.ws) - midOf(key));
    span.set(key, w);
    return w;
  };
  const assign = (key: string, lvl: number): number => {
    level.set(key, lvl);
    grow(lvl, (box.get(key) as { h: number }).h);
    const st = stacks.get(key);
    if (st) grow(lvl + 1, st.h);
    let base = st ? lvl + 2 : lvl + 1;
    let used = st ? lvl + 1 : lvl;
    (rows.get(key) as string[][]).forEach((row, r) => {
      let rowMax = r === 0 ? used : base - 1;
      for (const c of row) rowMax = Math.max(rowMax, assign(c, base));
      used = rowMax;
      base = rowMax + 1;
    });
    return used;
  };
  const top: number[] = [];
  const pos = new Map<string, OrgNode>();
  const trunk = new Map<string, number>();
  const spine = new Map<string, number>();
  const place = (key: string, left: number): void => {
    const b = box.get(key) as { w: number; h: number };
    const st = stacks.get(key);
    const kids = inner.get(key) as string[];
    const own = span.get(key) as number;
    const lvl = level.get(key) as number;
    let x: number;
    let stackLeft = 0;
    if (st && !kids.length) {
      x = left + b.w / 2;
      stackLeft = x;
    } else {
      const sp = gutter.get(key) as number;
      const at0 = left + centreOf(key) - midOf(key);
      const centres: number[] = [];
      (rows.get(key) as string[][]).forEach((row, r) => {
        let at = at0 + sp;
        for (const c of row) {
          place(c, at);
          if (r === 0) centres.push((pos.get(c) as OrgNode).x);
          else spine.set(c, at0 + sp / 2);
          at += (span.get(c) as number) + GAP_X;
        }
      });
      x = centres.length ? ((centres[0] as number) + (centres[centres.length - 1] as number)) / 2 : left + own / 2;
      stackLeft = x;
    }
    pos.set(key, { key, x, y: (top[lvl] as number) + (levelH[lvl] as number) / 2, w: b.w, h: b.h, stacked: false });
    if (!st) return;
    st.leaves.forEach((c, i) => {
      const col = Math.floor(i / st.rows);
      const colLeft = stackLeft + col * (STACK_INDENT + st.colW + GAP_X) + STACK_INDENT;
      trunk.set(c, colLeft - STACK_INDENT);
      const y = (top[lvl + 1] as number) + st.rowH / 2 + (i % st.rows) * (st.rowH + STACK_GAP);
      pos.set(c, { key: c, x: colLeft + st.colW / 2, y, w: st.colW, h: st.rowH, stacked: true });
    });
  };
  for (const root of tree.roots) {
    measure(root);
    assign(root, 0);
  }
  levelH.forEach((_, d) => (top[d] = d === 0 ? 0 : (top[d - 1] as number) + (levelH[d - 1] as number) + GAP_Y));
  let left = 0;
  for (const root of tree.roots) {
    place(root, left);
    left += (span.get(root) as number) + GAP_X;
  }
  const width = Math.max(1, left - GAP_X);
  const nodes = tree.order.map((key) => pos.get(key) as OrgNode);
  const links: OrgLink[] = [];
  for (const key of tree.order) {
    const node = nodeOf(key);
    if (!node.parent) continue;
    const a = pos.get(node.parent) as OrgNode;
    const b = pos.get(key) as OrgNode;
    const y1 = a.y + a.h / 2;
    if (b.stacked) {
      const bus = (y1 + (top[(level.get(node.parent) as number) + 1] as number)) / 2;
      links.push({ from: node.parent, to: key, d: `M ${a.x} ${y1} V ${bus} H ${trunk.get(key)} V ${b.y} L ${b.x - b.w / 2} ${b.y}` });
      continue;
    }
    const y2 = b.y - b.h / 2;
    const gutterX = spine.get(key);
    if (gutterX !== undefined) {
      const pl = level.get(node.parent) as number;
      const first = stacks.has(node.parent) ? (top[pl + 2] as number) - GAP_Y / 2 : (y1 + (top[pl + 1] as number)) / 2;
      const bus = (top[level.get(key) as number] as number) - GAP_Y / 2;
      links.push({ from: node.parent, to: key, d: `M ${a.x} ${y1} V ${first} H ${gutterX} V ${bus} H ${b.x} V ${y2}` });
      continue;
    }
    if (stacks.has(node.parent)) {
      const bus = (top[level.get(key) as number] as number) - GAP_Y / 2;
      links.push({ from: node.parent, to: key, d: `M ${a.x} ${y1} V ${bus} H ${b.x} L ${b.x} ${y2}` });
      continue;
    }
    const mid = (y1 + y2) / 2;
    links.push({ from: node.parent, to: key, d: `M ${a.x} ${y1} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${y2}` });
  }
  const height = levelH.length ? (top[levelH.length - 1] as number) + (levelH[levelH.length - 1] as number) : 0;
  return { nodes, links, width, height };
}

export function fitView(layout: Pick<OrgLayout, 'width' | 'height'>, w: number, h: number): OrgView {
  const k = w > 0 && h > 0 ? clampZoom(Math.max(1, Math.min((w - 2 * FIT_PAD) / layout.width, (h - 2 * FIT_PAD) / layout.height))) : 1;
  const x = layout.width * k <= w ? (w - layout.width * k) / 2 : FIT_PAD;
  return { k, x, y: Math.max(FIT_PAD, (h - layout.height * k) / 2) };
}

export function clampZoom(k: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Number.isFinite(k) ? k : 1));
}

export function zoomAt(view: OrgView, factor: number, px: number, py: number): OrgView {
  const k = clampZoom(view.k * factor);
  const ratio = k / view.k;
  return { k, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio };
}

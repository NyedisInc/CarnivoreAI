import type { MdBlock, MdInline } from './task-manager-markdown';

export const ELLIPSIS = '…';

interface Budget {
  left: number;
  cut: boolean;
}

export function cutAtWord(text: string, max: number): string {
  if (text.length <= max) return text;
  const head = text.slice(0, max);
  const space = head.lastIndexOf(' ');
  return (space >= max / 2 ? head.slice(0, space) : head).trimEnd();
}

function clipNodes(nodes: MdInline[], budget: Budget): MdInline[] {
  const out: MdInline[] = [];
  for (const node of nodes) {
    if (budget.left <= 0) { budget.cut = true; break; }
    if (node.t === 'text' || node.t === 'code') {
      if (node.v.length <= budget.left) { out.push(node); budget.left -= node.v.length; continue; }
      const v = cutAtWord(node.v, budget.left);
      budget.left = 0;
      budget.cut = true;
      if (v) out.push({ ...node, v });
      break;
    }
    const c = clipNodes(node.c, budget);
    if (c.length) out.push({ ...node, c });
    if (budget.cut) break;
  }
  return out;
}

function inlineLength(nodes: MdInline[]): number {
  return nodes.reduce((n, node) => n + (node.t === 'text' || node.t === 'code' ? node.v.length : inlineLength(node.c)), 0);
}

export function clipInline(nodes: MdInline[], max: number, more = false): { nodes: MdInline[]; clipped: boolean } {
  const budget: Budget = { left: max > 0 ? max : Infinity, cut: false };
  const kept = clipNodes(nodes, budget);
  return { nodes: budget.cut || more ? [...kept, { t: 'text', v: ELLIPSIS }] : kept, clipped: budget.cut };
}

function clipRuns(runs: MdInline[][], budget: Budget): MdInline[][] {
  const out: MdInline[][] = [];
  for (const run of runs) {
    if (budget.left <= 0) { budget.cut = true; break; }
    out.push(clipNodes(run, budget));
    if (budget.cut) break;
  }
  return out;
}

function clipBlock(block: MdBlock, budget: Budget): MdBlock | null {
  switch (block.t) {
    case 'paragraph': {
      const lines = clipRuns(block.lines, budget);
      return lines.length ? { ...block, lines } : null;
    }
    case 'heading': {
      const c = clipNodes(block.c, budget);
      return c.length ? { ...block, c } : null;
    }
    case 'code': {
      if (block.text.length <= budget.left) { budget.left -= block.text.length; return block; }
      const text = block.text.slice(0, budget.left).trimEnd();
      budget.left = 0;
      budget.cut = true;
      return text ? { ...block, text, full: block.text } : null;
    }
    case 'list': {
      const items: typeof block.items = [];
      for (const item of block.items) {
        if (budget.left <= 0) { budget.cut = true; break; }
        const c = clipNodes(item.c, budget);
        const sub = item.sub && !budget.cut ? { ...item.sub, items: clipRuns(item.sub.items, budget) } : undefined;
        items.push(sub && sub.items.length ? { c, sub } : { c });
        if (budget.cut) break;
      }
      return items.length ? { ...block, items } : null;
    }
    case 'table': {
      const rows: MdInline[][][] = [];
      budget.left -= block.head.reduce((n, cell) => n + inlineLength(cell), 0);
      for (const row of block.rows) {
        const cost = row.reduce((n, cell) => n + inlineLength(cell), 0);
        if (cost > budget.left) { budget.cut = true; break; }
        rows.push(row);
        budget.left -= cost;
      }
      if (budget.left <= 0) budget.cut = true;
      return { ...block, rows };
    }
    case 'kv': {
      const pairs: typeof block.pairs = [];
      for (const pair of block.pairs) {
        const cost = pair.k.length + inlineLength(pair.v);
        if (cost > budget.left) { budget.cut = true; break; }
        pairs.push(pair);
        budget.left -= cost;
      }
      return pairs.length ? { ...block, pairs } : null;
    }
  }
}

function withEllipsis(blocks: MdBlock[]): MdBlock[] {
  const mark: MdInline = { t: 'text', v: ELLIPSIS };
  const last = blocks.at(-1);
  const rest = blocks.slice(0, -1);
  if (last?.t === 'paragraph') return [...rest, { ...last, lines: [...last.lines.slice(0, -1), [...(last.lines.at(-1) ?? []), mark]] }];
  if (last?.t === 'heading') return [...rest, { ...last, c: [...last.c, mark] }];
  if (last?.t === 'list') {
    const item = last.items.at(-1);
    if (item && !item.sub) return [...rest, { ...last, items: [...last.items.slice(0, -1), { c: [...item.c, mark] }] }];
  }
  return [...blocks, { t: 'paragraph', lines: [[mark]] }];
}

export function clipBlocks(blocks: MdBlock[], max: number, more = false): MdBlock[] {
  if (max <= 0 && !more) return blocks;
  const budget: Budget = { left: max > 0 ? max : Infinity, cut: false };
  const out: MdBlock[] = [];
  for (const block of blocks) {
    if (budget.left <= 0) { budget.cut = true; break; }
    const kept = clipBlock(block, budget);
    if (kept) out.push(kept);
    if (budget.cut) break;
  }
  return budget.cut || more ? withEllipsis(out) : out;
}

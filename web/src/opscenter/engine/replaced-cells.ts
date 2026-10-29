
import declarations from '../../../../src/data/widgets.json';
import { repairSpans } from './spans';
import type { LayoutPage, SlotId } from './types';
import { canonicalize, leavesOf, splitsOf } from './v7/tree';
import type { LayoutNode, SplitId } from './v7/types';

const CORE = 'core.';

export const REPLACED_CELLS: Readonly<Record<string, readonly string[]>> = Object.fromEntries(
  Object.entries((declarations as { replaced?: Record<string, string[]> }).replaced ?? {}).map(([from, to]) => [
    from.slice(CORE.length),
    to.map((id) => id.slice(CORE.length)),
  ]),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function namedIds(raw: Record<string, unknown>): Set<string> {
  const out = new Set<string>();
  for (const row of Array.isArray(raw['rows']) ? raw['rows'] : []) {
    for (const slot of isRecord(row) && Array.isArray(row['slots']) ? row['slots'] : []) {
      if (isRecord(slot) && typeof slot['id'] === 'string') out.add(slot['id']);
    }
  }
  if (isRecord(raw['variants'])) {
    for (const variant of Object.values(raw['variants'])) {
      const root = isRecord(variant) ? variant['root'] : null;
      if (isRecord(root)) for (const id of leavesOf(root as unknown as LayoutNode)) out.add(id);
    }
  }
  for (const id of Array.isArray(raw['hidden']) ? raw['hidden'] : []) if (typeof id === 'string') out.add(id);
  return out;
}

function swapList(list: unknown, fresh: (from: string) => readonly string[]): unknown {
  if (!Array.isArray(list) || !list.some((id) => typeof id === 'string' && id in REPLACED_CELLS)) return list;
  return list.flatMap((id) => (typeof id === 'string' && id in REPLACED_CELLS ? fresh(id) : [id]));
}

function freeSplitId(root: LayoutNode): SplitId {
  const used = splitsOf(root).map((split) => Number(split.id.slice(1)) || 0);
  return `s${(used.length ? Math.max(...used) : 0) + 1}`;
}

function swapTree(root: LayoutNode, fresh: (from: string) => readonly string[], page: LayoutPage): LayoutNode {
  let next = freeSplitId(root);
  const visit = (node: LayoutNode): LayoutNode | null => {
    if (node.t === 'leaf') {
      if (!(node.id in REPLACED_CELLS)) return node;
      const ids = fresh(node.id);
      if (ids.length === 0) return null;
      if (ids.length === 1) return { t: 'leaf', id: ids[0] as SlotId };
      const split: LayoutNode = {
        t: 'split',
        id: next,
        dir: 'h',
        unit: 'fr',
        sizes: ids.map(() => 1 / ids.length),
        children: ids.map((id) => ({ t: 'leaf', id: id as SlotId })),
      };
      next = `s${Number(next.slice(1)) + 1}`;
      return split;
    }
    const children: LayoutNode[] = [];
    const sizes: number[] = [];
    node.children.forEach((child, at) => {
      const made = visit(child);
      if (!made) return;
      children.push(made);
      sizes.push(node.sizes[at] ?? 0);
    });
    return { ...node, children, sizes };
  };
  const out = visit(root);
  return out ? canonicalize(out, page) : root;
}

export function replaceCells(raw: unknown, page: LayoutPage): { raw: unknown; migrated: boolean } {
  if (page !== 'home' || !isRecord(raw)) return { raw, migrated: false };
  const named = namedIds(raw);
  if (![...named].some((id) => id in REPLACED_CELLS)) return { raw, migrated: false };
  const placed = new Set<string>();
  const fresh = (from: string): readonly string[] =>
    (REPLACED_CELLS[from] ?? []).filter((id) => {
      if (named.has(id) || placed.has(id)) return false;
      placed.add(id);
      return true;
    });

  const out: Record<string, unknown> = { ...raw };
  if (raw['v'] === 6 && Array.isArray(raw['rows'])) {
    out['rows'] = raw['rows'].map((row) => {
      if (!isRecord(row) || !Array.isArray(row['slots'])) return row;
      const slots = row['slots'].flatMap((slot) => {
        if (!isRecord(slot) || typeof slot['id'] !== 'string' || !(slot['id'] in REPLACED_CELLS)) return [slot];
        const ids = fresh(slot['id']);
        const share = typeof slot['fr'] === 'number' && ids.length ? slot['fr'] / ids.length : 0;
        return ids.map((id) => ({ id, fr: share }));
      });
      return { ...row, slots };
    });
  } else if (raw['v'] === 7 && isRecord(raw['variants'])) {
    const variants: Record<string, unknown> = {};
    for (const [name, variant] of Object.entries(raw['variants'])) {
      const root = isRecord(variant) ? variant['root'] : null;
      variants[name] = isRecord(root)
        ? { ...(variant as Record<string, unknown>), root: swapTree(root as unknown as LayoutNode, fresh, page) }
        : variant;
    }
    out['variants'] = variants;
  }
  out['hidden'] = swapList(raw['hidden'], fresh);
  out['collapsed'] = swapList(raw['collapsed'], (from) => REPLACED_CELLS[from] ?? []);
  const fixed = out['v'] === 6 ? repairSpans(out as never) : out;
  return { raw: fixed, migrated: true };
}

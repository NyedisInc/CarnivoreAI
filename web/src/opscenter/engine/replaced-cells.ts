
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

const HOME_ONLY = new Set<string>(['stats']);

function appliesOn(page: LayoutPage, id: string): boolean {
  return page === 'home' || !HOME_ONLY.has(id);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function placedIds(raw: Record<string, unknown>): Set<string> {
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
  return out;
}

function namedIds(raw: Record<string, unknown>): Set<string> {
  const out = placedIds(raw);
  for (const id of Array.isArray(raw['hidden']) ? raw['hidden'] : []) if (typeof id === 'string') out.add(id);
  return out;
}

function swapList(list: unknown, fresh: (from: string) => readonly string[], table: Record<string, readonly string[]>): unknown {
  if (!Array.isArray(list) || !list.some((id) => typeof id === 'string' && id in table)) return list;
  return list.flatMap((id) => (typeof id === 'string' && id in table ? fresh(id) : [id]));
}

function freeSplitId(root: LayoutNode): SplitId {
  const used = splitsOf(root).map((split) => Number(split.id.slice(1)) || 0);
  return `s${(used.length ? Math.max(...used) : 0) + 1}`;
}

function swapTree(root: LayoutNode, fresh: (from: string) => readonly string[], page: LayoutPage, table: Record<string, readonly string[]>): LayoutNode {
  let next = freeSplitId(root);
  const visit = (node: LayoutNode): LayoutNode | null => {
    if (node.t === 'leaf') {
      if (!(node.id in table)) return node;
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
  if (!isRecord(raw)) return { raw, migrated: false };
  const table: Record<string, readonly string[]> = Object.fromEntries(Object.entries(REPLACED_CELLS).filter(([from]) => appliesOn(page, from)));
  const named = namedIds(raw);
  if (![...named].some((id) => id in table)) return { raw, migrated: false };
  const placedBefore = placedIds(raw);
  const placed = new Set<string>();
  const fresh = (from: string): readonly string[] => {
    const successors = table[from] ?? [];
    const blocked = successors.length === 1 ? placedBefore : named;
    return successors.filter((id) => {
      if (blocked.has(id) || placed.has(id)) return false;
      placed.add(id);
      return true;
    });
  };

  const out: Record<string, unknown> = { ...raw };
  if (raw['v'] === 6 && Array.isArray(raw['rows'])) {
    out['rows'] = raw['rows'].map((row) => {
      if (!isRecord(row) || !Array.isArray(row['slots'])) return row;
      const slots = row['slots'].flatMap((slot) => {
        if (!isRecord(slot) || typeof slot['id'] !== 'string' || !(slot['id'] in table)) return [slot];
        const ids = fresh(slot['id']);
        const share = typeof slot['fr'] === 'number' && ids.length ? slot['fr'] / ids.length : 0;
        return ids.map((id) => ({ ...(ids.length === 1 ? slot : {}), id, fr: share }));
      });
      return { ...row, slots };
    });
    out['rows'] = (out['rows'] as unknown[]).filter((row) => !(isRecord(row) && Array.isArray(row['slots']) && row['slots'].length === 0));
  } else if (raw['v'] === 7 && isRecord(raw['variants'])) {
    const variants: Record<string, unknown> = {};
    for (const [name, variant] of Object.entries(raw['variants'])) {
      const root = isRecord(variant) ? variant['root'] : null;
      variants[name] = isRecord(root)
        ? { ...(variant as Record<string, unknown>), root: swapTree(root as unknown as LayoutNode, fresh, page, table) }
        : variant;
    }
    out['variants'] = variants;
  }
  const hidden = swapList(raw['hidden'], (from) => table[from] ?? [], table);
  const nowPlaced = new Set<string>([...placedBefore, ...placed]);
  out['hidden'] = Array.isArray(hidden)
    ? hidden.filter((id, at) => !(typeof id === 'string' && nowPlaced.has(id)) && hidden.indexOf(id) === at)
    : hidden;
  const collapsed = swapList(raw['collapsed'], (from) => table[from] ?? [], table);
  out['collapsed'] = Array.isArray(collapsed) ? collapsed.filter((id, at) => collapsed.indexOf(id) === at) : collapsed;
  if ('headerOff' in raw) {
    const headerOff = swapList(raw['headerOff'], (from) => table[from] ?? [], table);
    out['headerOff'] = Array.isArray(headerOff) ? headerOff.filter((id, at) => headerOff.indexOf(id) === at) : headerOff;
  }
  const fixed = out['v'] === 6 ? repairSpans(out as never) : out;
  return { raw: fixed, migrated: true };
}

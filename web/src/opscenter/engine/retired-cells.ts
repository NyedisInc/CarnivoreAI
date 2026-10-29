
import { repairSpans } from './spans';
import type { LayoutPage, SlotId } from './types';
import { removeLeaf } from './v7/tree';
import type { LayoutNode } from './v7/types';

export const RETIRED_HOME_CELLS: readonly string[] = ['hero'];

export const RETIRED_EVERY_PAGE_CELLS: readonly string[] = ['save-pipeline'];

function retiredFor(page: LayoutPage): readonly string[] {
  return page === 'home' ? [...RETIRED_HOME_CELLS, ...RETIRED_EVERY_PAGE_CELLS] : RETIRED_EVERY_PAGE_CELLS;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function withoutRetired(list: unknown, retired: readonly string[]): unknown {
  if (!Array.isArray(list)) return list;
  return list.some((id) => retired.includes(id as string)) ? list.filter((id) => !retired.includes(id as string)) : list;
}

function plausibleRow(row: unknown): row is Record<string, unknown> & { slots: unknown[] } {
  return isRecord(row) && Array.isArray(row['slots']) && row['slots'].every(isRecord);
}

export function dropRetiredCells(raw: unknown, page: LayoutPage): { raw: unknown; migrated: boolean } {
  if (!isRecord(raw)) return { raw, migrated: false };
  const retired = retiredFor(page);
  const hidden = withoutRetired(raw['hidden'], retired);
  const collapsed = withoutRetired(raw['collapsed'], retired);
  const headerOff = raw['headerOff'] === undefined ? undefined : withoutRetired(raw['headerOff'], retired);
  const listsChanged = hidden !== raw['hidden'] || collapsed !== raw['collapsed'] || headerOff !== raw['headerOff'];
  const base = listsChanged ? { ...raw, hidden, collapsed, ...(headerOff === undefined ? {} : { headerOff }) } : raw;

  if (raw['v'] === 6 && Array.isArray(raw['rows']) && raw['rows'].every(plausibleRow)) {
    const rows = raw['rows'] as Array<Record<string, unknown> & { slots: Array<Record<string, unknown>> }>;
    const held = rows.some((row) => row.slots.some((slot) => retired.includes(slot['id'] as string)));
    if (!held) return { raw: base, migrated: listsChanged };
    const kept = rows.map((row) => ({
      ...row,
      slots: row.slots.filter((slot) => !retired.includes(slot['id'] as string)),
    }));
    const fixed = repairSpans({ ...base, rows: kept } as never);
    return { raw: fixed, migrated: true };
  }

  if (raw['v'] === 7 && isRecord(raw['variants'])) {
    const variants: Record<string, unknown> = {};
    let held = false;
    for (const [name, variant] of Object.entries(raw['variants'])) {
      const root = isRecord(variant) ? variant['root'] : null;
      if (!isRecord(root)) return { raw: base, migrated: listsChanged };
      let next: LayoutNode | null = root as unknown as LayoutNode;
      for (const id of retired) next = next ? removeLeaf(next, id as SlotId, page) : null;
      const changed = next !== null && next !== (root as unknown);
      if (changed) held = true;
      variants[name] = changed ? { ...(variant as Record<string, unknown>), root: next } : variant;
    }
    return held ? { raw: { ...base, variants }, migrated: true } : { raw: base, migrated: listsChanged };
  }
  return { raw: base, migrated: listsChanged };
}

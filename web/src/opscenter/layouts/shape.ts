import { PRIMARY_SLOT } from '../engine/model';
import { isTabSlot, tabsOf, type TabGroups } from '../engine/tabs';
import { isPageSlot } from '../engine/page-tabs';
import { isNonSessionTab } from '../engine/widget-tabs';
import type { Layout, RowModel, SlotId } from '../engine/types';
import { readStoredGrid } from '../engine/v7/adapt';
import type { LayoutShape } from './api';

export const NAME_MAX = 60;

export const LAYOUT_LIMIT = 100;

const CONTROL_RX = /[\x00-\x1F\x7F-\x9F]/;

export function rowSlot(rowId: number): string {
  return `terminal:row:${rowId}`;
}

export function terminalComponents(layout: Layout): string[] {
  const out: string[] = [];
  for (const row of layout.rows) {
    for (const slot of row.slots) {
      if (isTabSlot(slot.id) && !isPageSlot(slot.id) && !out.includes(slot.id)) out.push(slot.id);
    }
  }
  return out;
}

export function storedComponents(layout: Layout): string[] {
  const out: string[] = [];
  for (const row of layout.rows) {
    for (const slot of row.slots) if (isTabSlot(slot.id) && !out.includes(slot.id)) out.push(slot.id);
  }
  return out;
}

export function displayedTabs(layout: Layout, groups: TabGroups): string[] {
  const seen: string[] = [];
  for (const component of terminalComponents(layout)) {
    for (const tab of tabsOf(groups, component)) if (!isNonSessionTab(tab) && !seen.includes(tab)) seen.push(tab);
  }
  return seen;
}

export function visibleTerminals(layout: Layout): number {
  return terminalComponents(layout).length;
}

export function toServerShape(layout: Layout, groups: TabGroups, anchorRowId: number): LayoutShape {
  const anchor = rowSlot(anchorRowId);
  const out: TabGroups = {};
  for (const component of storedComponents(layout)) {
    out[component] = { tabs: tabsOf(groups, component).map((tab) => (tab === PRIMARY_SLOT ? anchor : tab)) };
  }
  return { layout: structuredClone(layout), groups: out };
}

function gridOf(components: string[]): Layout {
  const share = components.length > 0 ? 1 / components.length : 1;
  const row: RowModel = {
    id: 'r1',
    kind: 'flex',
    size: 1,
    slots: components.map((id) => ({ id: id as SlotId, fr: share })),
  };
  return { v: 6, rows: [row], hidden: [], heroCollapsed: false, collapsed: [] };
}

function renameSlot(layout: Layout, from: string, to: string): Layout {
  const swap = (id: SlotId): SlotId => (id === from ? (to as SlotId) : id);
  return {
    ...layout,
    rows: layout.rows.map((row) => ({
      ...row,
      slots: row.slots.map((slot) => ({ ...slot, id: swap(slot.id) })),
      ...(row.reserved ? { reserved: row.reserved.map((one) => ({ ...one, of: swap(one.of) })) } : {}),
    })),
    hidden: layout.hidden.map(swap),
    collapsed: layout.collapsed.map(swap),
    ...(layout.headerOff ? { headerOff: layout.headerOff.map(swap) } : {}),
  };
}

function freeKey(layout: Layout, candidates: string[]): string {
  const taken = new Set([...layout.rows.flatMap((row) => row.slots.map((slot) => slot.id as string)), ...layout.hidden]);
  const found = candidates.find((id) => isTabSlot(id) && id !== PRIMARY_SLOT && !taken.has(id));
  if (found) return found;
  let n = 1;
  while (taken.has(`terminal:c${n}`)) n += 1;
  return `terminal:c${n}`;
}

export function fromServerShape(shape: LayoutShape, anchorRowId: number): LayoutShape | null {
  const anchor = rowSlot(anchorRowId);
  const stored = shape.layout ? readStoredGrid(shape.layout, 'terminal') : null;
  const grid = stored?.kind === 'v7' ? stored.grid : stored?.kind === 'v6' ? (stored.grid as Layout) : null;
  let layout: Layout = grid ? structuredClone(grid) : gridOf(Object.keys(shape.groups ?? {}));
  const source = shape.groups ?? {};
  let groups: TabGroups = {};
  for (const component of storedComponents(layout)) groups[component] = { tabs: [...tabsOf(source, component)] };
  const holder = Object.keys(groups).find((component) => groups[component]!.tabs.includes(anchor));
  if (!holder) return null;
  if (holder !== PRIMARY_SLOT) {
    if (groups[PRIMARY_SLOT]) {
      const moved = freeKey(layout, groups[PRIMARY_SLOT].tabs);
      layout = renameSlot(layout, PRIMARY_SLOT, moved);
      groups = { ...groups, [moved]: groups[PRIMARY_SLOT] };
      delete groups[PRIMARY_SLOT];
    }
    layout = renameSlot(layout, holder, PRIMARY_SLOT);
    groups = { ...groups, [PRIMARY_SLOT]: groups[holder]! };
    delete groups[holder];
  }
  groups[PRIMARY_SLOT] = { tabs: groups[PRIMARY_SLOT]!.tabs.map((tab) => (tab === anchor ? PRIMARY_SLOT : tab)) };
  return { layout, groups };
}

export function nameProblem(name: string): 'empty' | 'too_long' | 'invalid' | null {
  const trimmed = name.trim();
  if (!trimmed) return 'empty';
  if ([...trimmed].length > NAME_MAX) return 'too_long';
  if (CONTROL_RX.test(trimmed)) return 'invalid';
  return null;
}

export function freeName(base: string, taken: readonly string[], numbered: (name: string, n: number) => string): string {
  const folded = new Set(taken.map((one) => one.trim().toLocaleLowerCase()));
  const plain = base.trim().slice(0, NAME_MAX);
  if (!folded.has(plain.toLocaleLowerCase())) return plain;
  for (let n = 2; n < 1000; n += 1) {
    const candidate = numbered(plain, n).slice(0, NAME_MAX);
    if (!folded.has(candidate.toLocaleLowerCase())) return candidate;
  }
  return plain;
}

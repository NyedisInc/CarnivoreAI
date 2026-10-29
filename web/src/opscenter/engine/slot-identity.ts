import { PRIMARY_SLOT, removeCell } from './model';
import { instanceName } from './meta';
import type { ActiveTabs, TabGroups } from './tabs';
import type { Arrangement, ArrangementEntry } from './arrangement-model';
import type { Layout, SlotId } from './types';
import { isPageSlot } from './page-tabs';

const TERMINAL = 'terminal:';

export const ROW_TAIL = 'row:';

export interface SlotRow {
  session?: { id?: string } | null;
  session_row_id?: number | null;
}

export function rowIdOfSlot(slot: string): number | null {
  if (typeof slot !== 'string' || !slot.startsWith(TERMINAL + ROW_TAIL)) return null;
  const digits = slot.slice(TERMINAL.length + ROW_TAIL.length);
  return /^\d{1,15}$/.test(digits) ? Number(digits) : null;
}

export function sessionForSlot(slot: string, rows: readonly SlotRow[] | null | undefined): string {
  const tail = instanceName(slot as SlotId);
  const rowId = rowIdOfSlot(slot);
  if (rowId === null || !rows) return tail;
  return rows.find((row) => row.session_row_id === rowId)?.session?.id ?? tail;
}

export function slotNameFor(sessionId: string, rows: readonly SlotRow[] | null | undefined): string {
  const rowId = rows?.find((row) => row.session?.id === sessionId)?.session_row_id;
  return typeof rowId === 'number' && Number.isFinite(rowId) ? `${ROW_TAIL}${rowId}` : sessionId;
}

export function slotForSession(sessionId: string, rows: readonly SlotRow[] | null | undefined): string {
  return TERMINAL + slotNameFor(sessionId, rows);
}

export function slotRenames(
  ids: Iterable<string>,
  rows: readonly SlotRow[],
  drop: boolean,
): Map<string, string | null> {
  const present = new Set(ids);
  const renames = new Map<string, string | null>();
  for (const id of present) {
    if (!id.startsWith(TERMINAL) || id === PRIMARY_SLOT || rowIdOfSlot(id) !== null || isPageSlot(id)) continue;
    const tail = id.slice(TERMINAL.length);
    const live = rows.find((row) => row.session?.id === tail);
    if (live) {
      if (typeof live.session_row_id !== 'number') continue;
      const next = `${TERMINAL}${ROW_TAIL}${live.session_row_id}`;
      renames.set(id, present.has(next) ? null : next);
    } else if (drop) {
      renames.set(id, null);
    }
  }
  return renames;
}

export interface SlotEntry {
  layout: Layout | null;
  groups: TabGroups;
  active: ActiveTabs;
}

export interface RekeyResult extends SlotEntry {
  changed: boolean;
  dropped: number;
}

function idsOf(entry: SlotEntry): string[] {
  const ids: string[] = [];
  for (const row of entry.layout?.rows ?? []) for (const slot of row.slots ?? []) ids.push(slot.id);
  ids.push(...(entry.layout?.hidden ?? []), ...(entry.layout?.collapsed ?? []));
  for (const [slot, group] of Object.entries(entry.groups)) ids.push(slot, ...group.tabs);
  for (const [slot, tab] of Object.entries(entry.active)) ids.push(slot, tab);
  return ids;
}

export function rekeyEntry(entry: SlotEntry, rows: readonly SlotRow[], drop: boolean): RekeyResult {
  const renames = slotRenames(idsOf(entry), rows, drop);
  if (renames.size === 0) return { ...entry, changed: false, dropped: 0 };
  const tab = (id: string): string | null => (renames.has(id) ? renames.get(id)! : id);

  const components = new Map<string, string | null>();
  const groups: TabGroups = {};
  for (const [slot, group] of Object.entries(entry.groups)) {
    const tabs = group.tabs.map(tab).filter((one): one is string => one !== null);
    if (slot === PRIMARY_SLOT) {
      if (tabs.length > 0) groups[slot] = { tabs };
      continue;
    }
    const name = tabs.length === 0 ? null : (tab(slot) ?? slot);
    components.set(slot, name);
    if (name !== null) groups[name] = { tabs };
  }
  const component = (id: string): string | null =>
    components.has(id) ? components.get(id)! : id === PRIMARY_SLOT ? id : tab(id);

  let layout = entry.layout;
  if (layout) {
    let next: Layout = {
      ...layout,
      rows: layout.rows.map((row) => ({
        ...row,
        slots: row.slots.map((slot) => ({ ...slot, id: (component(slot.id) ?? slot.id) as SlotId })),
        ...(row.reserved
          ? { reserved: row.reserved.map((one) => ({ ...one, of: (component(one.of) ?? one.of) as SlotId })) }
          : {}),
      })),
      hidden: (layout.hidden ?? []).filter((id) => component(id) !== null).map((id) => component(id) as SlotId),
      collapsed: (layout.collapsed ?? []).filter((id) => component(id) !== null).map((id) => component(id) as SlotId),
    };
    for (const row of layout.rows) {
      for (const slot of row.slots) if (component(slot.id) === null) next = removeCell(next, slot.id);
    }
    layout = next;
  }

  const active: ActiveTabs = {};
  for (const [slot, shown] of Object.entries(entry.active)) {
    const key = component(slot);
    const value = tab(shown);
    if (key !== null && value !== null) active[key] = value;
  }

  const dropped = [...renames.values()].filter((one) => one === null).length;
  return { layout, groups, active, changed: true, dropped };
}

export function rekeyArrangement(
  map: Arrangement,
  rows: readonly SlotRow[],
  drop: boolean,
): { map: Arrangement; dropped: number } {
  let changed = false;
  let dropped = 0;
  const sessions: Record<string, ArrangementEntry> = {};
  for (const [key, entry] of Object.entries(map.sessions)) {
    sessions[key] = entry;
    try {
      const result = rekeyEntry({ layout: entry.layout, groups: entry.groups, active: {} }, rows, drop);
      if (!result.changed) continue;
      changed = true;
      dropped += result.dropped;
      sessions[key] = { layout: result.layout, groups: result.groups };
    } catch (error) {
      console.warn('[terminal tabs] kept an unreadable arrangement entry as sent', key, error);
    }
  }
  return changed ? { map: { v: 1, sessions }, dropped } : { map, dropped: 0 };
}

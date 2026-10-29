import {
  activeOf, addTab, closeTab, findTab, mergeGroup, moveTab, normalize, splitOut, tabsOf, type ActiveTabs, type TabGroups,
} from './tabs';
import { freeSlot } from './tab-split';
import { PRIMARY_SLOT } from './model';
import { takenSlots } from './components-actions';
import type { SlotId } from './types';
import type { DropTarget, LayoutStore } from './layout.svelte';
import { arrangementChanged } from './arrangement-events';
import { isLayoutKey } from './session-layouts';
import { pageSlotFor } from './page-tabs';

export const TABS_KEY_PREFIX = 'cloudecode.opscenter.tabs.v1:';

interface Stored {
  groups: TabGroups;
  active: ActiveTabs;
}

const cache = new Map<string, Stored>();
let revision = $state(0);

function empty(): Stored {
  return { groups: {}, active: {} };
}

function read(key: string): Stored {
  try {
    const raw = globalThis.localStorage?.getItem(TABS_KEY_PREFIX + key);
    if (!raw) return empty();
    const parsed = JSON.parse(raw) as Partial<Stored>;
    const groups: TabGroups = {};
    for (const [slot, group] of Object.entries(parsed.groups ?? {})) {
      const tabs = Array.isArray(group?.tabs) ? group.tabs.filter((t) => typeof t === 'string') : [];
      groups[slot] = { tabs };
    }
    const active: ActiveTabs = {};
    for (const [slot, tab] of Object.entries(parsed.active ?? {})) {
      if (typeof tab === 'string') active[slot] = tab;
    }
    return { groups, active };
  } catch {
    return empty();
  }
}

function recordFor(store: LayoutStore): Stored {
  void store.state.layout;
  void revision;
  return recordByKey(store.session);
}

export function tabsFor(store: LayoutStore, slot: string): string[] {
  return tabsOf(recordFor(store).groups, slot);
}

export function activeTabFor(store: LayoutStore, slot: string): string {
  const record = recordFor(store);
  return activeOf(record.groups, record.active, slot);
}

export function selectTab(store: LayoutStore, slot: string, tab: string): void {
  const record = recordFor(store);
  if (!tabsOf(record.groups, slot).includes(tab)) return;
  record.active[slot] = tab;
  persist(store.session, record);
}

export function openTab(store: LayoutStore, slot: string, tab: string): string {
  const record = recordFor(store);
  const groups = normalize(record.groups, [...new Set([...takenSlots(store), slot])]).groups;
  const holder = findTab(groups, tab) ?? slot;
  if (store.state.layout.hidden.includes(holder as SlotId)) store.show(holder as SlotId);
  record.groups = holder === slot ? addTab(groups, slot, tab) : groups;
  record.active[holder] = tab;
  persist(store.session, record);
  return holder;
}

export function removeTab(store: LayoutStore, tab: string): string | null {
  const record = recordFor(store);
  const groups = normalize(record.groups, takenSlots(store)).groups;
  const slot = findTab(groups, tab);
  if (slot === null) return null;
  const { groups: next, emptied } = closeTab(groups, tab);
  handOnActive(record, groups, slot, tab);
  record.groups = next;
  persist(store.session, record);
  if (emptied) store.remove(emptied as SlotId);
  return emptied;
}

export function replaceTab(store: LayoutStore, from: string, to: string): boolean {
  const record = recordFor(store);
  const groups = normalize(record.groups, takenSlots(store)).groups;
  const slot = findTab(groups, from);
  if (slot === null || findTab(groups, to) !== null) return false;
  const showing = activeOf(groups, record.active, slot) === from;
  record.groups = { ...groups, [slot]: { tabs: tabsOf(groups, slot).map((tab) => (tab === from ? to : tab)) } };
  if (showing) record.active[slot] = to;
  persist(store.session, record);
  return true;
}

function handOnActive(record: Stored, groups: TabGroups, slot: string, tab: string): void {
  if (activeOf(groups, record.active, slot) !== tab) return;
  const before = tabsOf(groups, slot);
  const at = before.indexOf(tab);
  const neighbour = before[at + 1] ?? before[at - 1];
  if (neighbour) record.active[slot] = neighbour;
  else delete record.active[slot];
}

export function placeTab(store: LayoutStore, slot: string, tab: string, index: number): 'moved' | 'added' | null {
  const record = recordFor(store);
  const groups = normalize(record.groups, takenSlots(store)).groups;
  if (!groups[slot]) return null;
  const from = findTab(groups, tab);
  const { groups: next, emptied } =
    from === null ? { groups: addTab(groups, slot, tab, index), emptied: null } : moveTab(groups, tab, slot, index);
  if (emptied === PRIMARY_SLOT) return null;
  if (from !== null && from !== slot) handOnActive(record, groups, from, tab);
  if (emptied) delete record.active[emptied];
  record.groups = next;
  record.active[slot] = tab;
  persist(store.session, record);
  if (emptied) store.remove(emptied as SlotId);
  return from === null ? 'added' : 'moved';
}

export function splitTabOut(store: LayoutStore, tab: string, target: DropTarget): 'split' | 'moved' | 'cap' | 'limit' | null {
  const record = recordFor(store);
  const taken = takenSlots(store);
  const groups = normalize(record.groups, taken).groups;
  const from = findTab(groups, tab);
  const source = from === null ? [] : tabsOf(groups, from);
  if (from !== null && source.length === 1) return store.moveTo(from as SlotId, target) ? 'moved' : null;
  const everyTab = Object.values(groups).flatMap((group) => group.tabs);
  const slot = pageSlotFor(tab, taken) ?? freeSlot(taken, [tab, ...source, ...everyTab]);
  if (!slot) return null;
  const before: Stored = { groups: record.groups, active: { ...record.active } };
  const layout = store.snapshot();
  if (from !== null) handOnActive(record, groups, from, tab);
  record.groups = splitOut(groups, tab, slot).groups;
  record.active[slot] = tab;
  persist(store.session, record);
  const refusal = store.add('terminal', slot.slice('terminal:'.length));
  const landed = !refusal && store.moveTo(slot as SlotId, target);
  if (landed) return 'split';
  if (!refusal) store.restore(layout);
  record.groups = before.groups;
  record.active = before.active;
  persist(store.session, record);
  return refusal === 'cap' || refusal === 'limit' ? refusal : null;
}

export function mergeComponent(store: LayoutStore, from: string, into: string): 'merged' | 'primary' | null {
  if (from === into) return null;
  if (from === PRIMARY_SLOT) return 'primary';
  const record = recordFor(store);
  const groups = normalize(record.groups, takenSlots(store)).groups;
  if (!groups[from] || !groups[into]) return null;
  const shown = activeOf(groups, record.active, from);
  record.groups = mergeGroup(groups, from, into);
  delete record.active[from];
  record.active[into] = shown;
  persist(store.session, record);
  store.remove(from as SlotId);
  return 'merged';
}

export function setGroups(store: LayoutStore, groups: TabGroups): void {
  const record = recordFor(store);
  record.groups = groups;
  persist(store.session, record);
}

function persist(key: string, record: Stored): void {
  revision += 1;
  if (!key) return;
  try {
    globalThis.localStorage?.setItem(
      TABS_KEY_PREFIX + key,
      JSON.stringify({ groups: record.groups, active: record.active }),
    );
  } catch {
  }
  arrangementChanged(key);
}

function recordByKey(key: string): Stored {
  let record = cache.get(key);
  if (!record) {
    record = read(key);
    cache.set(key, record);
  }
  return record;
}

export function groupsFor(key: string): TabGroups {
  return recordByKey(key).groups;
}

export function adoptGroups(key: string, groups: TabGroups): void {
  const record = recordByKey(key);
  record.groups = groups;
  persist(key, record);
}

export function activeTabsFor(key: string): ActiveTabs {
  return recordByKey(key).active;
}

export function replaceTabs(key: string, groups: TabGroups, active: ActiveTabs): void {
  const record = recordByKey(key);
  record.groups = groups;
  record.active = active;
  persist(key, record);
}

export function cloneTabs(from: string, to: string): void {
  if (!to || from === to) return;
  const source = recordByKey(from);
  const record = recordByKey(to);
  record.groups = JSON.parse(JSON.stringify(source.groups)) as TabGroups;
  record.active = { ...source.active };
  persist(to, record);
}

export function forgetTabs(key: string): void {
  cache.delete(key);
  revision += 1;
  try {
    globalThis.localStorage?.removeItem(TABS_KEY_PREFIX + key);
  } catch {
  }
}

export function storedTabKeys(): string[] {
  const keys: string[] = [];
  try {
    const store = globalThis.localStorage;
    for (let i = 0; store && i < store.length; i += 1) {
      const name = store.key(i);
      if (name?.startsWith(TABS_KEY_PREFIX) && !isLayoutKey(name.slice(TABS_KEY_PREFIX.length))) {
        keys.push(name.slice(TABS_KEY_PREFIX.length));
      }
    }
  } catch {
  }
  return keys;
}

export function resetTabCache(): void {
  cache.clear();
}

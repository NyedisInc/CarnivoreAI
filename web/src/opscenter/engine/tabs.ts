
export interface TabGroup {
  tabs: string[];
}

export type TabGroups = Record<string, TabGroup>;

export type ActiveTabs = Record<string, string>;

export function isTabSlot(slot: string): boolean {
  return slot.startsWith('terminal:');
}

export function findTab(groups: TabGroups, tab: string): string | null {
  for (const [slot, group] of Object.entries(groups)) {
    if (group.tabs.includes(tab)) return slot;
  }
  return null;
}

export function tabsOf(groups: TabGroups, slot: string): string[] {
  const tabs = groups[slot]?.tabs;
  return tabs && tabs.length > 0 ? tabs : [slot];
}

export function activeOf(groups: TabGroups, active: ActiveTabs, slot: string): string {
  const tabs = tabsOf(groups, slot);
  const chosen = active[slot];
  return chosen && tabs.includes(chosen) ? chosen : (tabs[0] ?? slot);
}

export function addTab(groups: TabGroups, slot: string, tab: string, index?: number): TabGroups {
  if (findTab(groups, tab) !== null) return groups;
  const tabs = [...tabsOf(groups, slot)];
  const at = index === undefined ? tabs.length : Math.max(0, Math.min(index, tabs.length));
  tabs.splice(at, 0, tab);
  return { ...groups, [slot]: { tabs } };
}

export function closeTab(groups: TabGroups, tab: string): { groups: TabGroups; emptied: string | null } {
  const slot = findTab(groups, tab);
  if (slot === null) return { groups, emptied: null };
  const tabs = tabsOf(groups, slot).filter((t) => t !== tab);
  const next = { ...groups, [slot]: { tabs } };
  return tabs.length === 0 ? { groups: next, emptied: slot } : { groups: next, emptied: null };
}

export function moveTab(
  groups: TabGroups,
  tab: string,
  toSlot: string,
  index?: number,
): { groups: TabGroups; emptied: string | null } {
  if (findTab(groups, tab) === null) return { groups, emptied: null };
  const without = closeTab(groups, tab);
  const target = [...(without.groups[toSlot]?.tabs ?? [])];
  const at = index === undefined ? target.length : Math.max(0, Math.min(index, target.length));
  target.splice(at, 0, tab);
  const next = { ...without.groups, [toSlot]: { tabs: target } };
  const emptied = without.emptied === toSlot ? null : without.emptied;
  return { groups: next, emptied };
}

export function splitOut(
  groups: TabGroups,
  tab: string,
  newSlot: string,
): { groups: TabGroups; emptied: string | null } {
  const without = closeTab(groups, tab);
  return { groups: { ...without.groups, [newSlot]: { tabs: [tab] } }, emptied: without.emptied };
}

export function mergeGroup(groups: TabGroups, fromSlot: string, intoSlot: string): TabGroups {
  if (fromSlot === intoSlot) return groups;
  const moving = tabsOf(groups, fromSlot);
  const into = tabsOf(groups, intoSlot);
  return { ...groups, [intoSlot]: { tabs: [...into, ...moving] }, [fromSlot]: { tabs: [] } };
}

export function migrate(slots: readonly string[]): TabGroups {
  const groups: TabGroups = {};
  for (const slot of slots) if (isTabSlot(slot)) groups[slot] = { tabs: [slot] };
  return groups;
}

export function normalize(groups: TabGroups, slots: readonly string[]): { groups: TabGroups; remove: string[] } {
  const next: TabGroups = {};
  const seen = new Set<string>();
  const remove: string[] = [];
  for (const slot of slots) {
    if (!isTabSlot(slot)) continue;
    const tabs = (groups[slot] ? groups[slot].tabs : [slot]).filter((t) => {
      if (seen.has(t)) return false;
      seen.add(t);
      return true;
    });
    next[slot] = { tabs };
    if (tabs.length === 0) remove.push(slot);
  }
  return { groups: next, remove };
}

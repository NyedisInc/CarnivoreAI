import type { ArrangementEntry, Arrangement } from './arrangement-model';
import type { Board } from './home-boards';
import { replaceCells } from './replaced-cells';
import type { TabGroups } from './tabs';
import type { Layout } from './types';
import { widgetIdOfTab, widgetTabId, widgetTargetOfTab } from './widget-tabs';

export function retireTab(tab: string): string {
  const id = widgetIdOfTab(tab);
  return id ? widgetTabId(id, widgetTargetOfTab(tab)) : tab;
}

export function retireGroups(groups: TabGroups): TabGroups {
  let changed = false;
  const out: TabGroups = {};
  for (const [slot, group] of Object.entries(groups)) {
    const tabs = group.tabs.map(retireTab);
    if (tabs.every((tab, at) => tab === group.tabs[at])) {
      out[slot] = group;
      continue;
    }
    changed = true;
    out[slot] = { ...group, tabs: tabs.filter((tab, at) => tabs.indexOf(tab) === at) };
  }
  return changed ? out : groups;
}

export function retireEntry(entry: ArrangementEntry): ArrangementEntry {
  const replaced = entry.layout ? replaceCells(entry.layout, 'terminal') : null;
  const groups = retireGroups(entry.groups);
  if (!replaced?.migrated && groups === entry.groups) return entry;
  return { layout: replaced?.migrated ? (replaced.raw as Layout) : entry.layout, groups };
}

export function retireArrangement(map: Arrangement): { map: Arrangement; changed: string[] } {
  const changed: string[] = [];
  const sessions: Arrangement['sessions'] = {};
  for (const [key, entry] of Object.entries(map.sessions)) {
    const next = retireEntry(entry);
    if (next !== entry) changed.push(key);
    sessions[key] = next;
  }
  return changed.length ? { map: { ...map, sessions }, changed } : { map, changed };
}

export function retireBoards(boards: Board[]): Board[] {
  let changed = false;
  const out = boards.map((board) => {
    const replaced = replaceCells(board.layout, 'home');
    if (!replaced.migrated) return board;
    changed = true;
    return { ...board, layout: replaced.raw as Layout };
  });
  return changed ? out : boards;
}

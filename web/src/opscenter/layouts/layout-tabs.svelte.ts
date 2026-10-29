
export const LAYOUT_TABS_KEY = 'cloude.layout_tabs';

export function withTab(tabs: readonly string[], uuid: string): string[] {
  return !uuid || tabs.includes(uuid) ? [...tabs] : [...tabs, uuid];
}

export function closeTab(
  tabs: readonly string[], uuid: string, active: string,
): { tabs: string[]; open: string | null } {
  const at = tabs.indexOf(uuid);
  if (at < 0 || tabs.length <= 1) return { tabs: [...tabs], open: null };
  const rest = tabs.filter((one) => one !== uuid);
  return { tabs: rest, open: uuid === active ? (rest[at] ?? rest[rest.length - 1] ?? null) : null };
}

export function addable<T extends { layout_uuid: string }>(all: readonly T[], tabs: readonly string[]): T[] {
  return all.filter((one) => !tabs.includes(one.layout_uuid));
}

export function visibleTabs(tabs: readonly string[], known: readonly string[] | null, active: string): string[] {
  return tabs.filter((uuid) => uuid === active || known === null || known.includes(uuid));
}

function load(): string[] {
  try {
    const raw: unknown = JSON.parse(globalThis.localStorage?.getItem(LAYOUT_TABS_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((one): one is string => typeof one === 'string') : [];
  } catch {
    return [];
  }
}

export const layoutTabs: { uuids: string[] } = $state({ uuids: load() });

export function setTabs(next: string[]): void {
  layoutTabs.uuids = next;
  try {
    globalThis.localStorage?.setItem(LAYOUT_TABS_KEY, JSON.stringify(next));
  } catch {
  }
}

export function noteOpen(uuid: string): void {
  if (uuid && !layoutTabs.uuids.includes(uuid)) setTabs(withTab(layoutTabs.uuids, uuid));
}

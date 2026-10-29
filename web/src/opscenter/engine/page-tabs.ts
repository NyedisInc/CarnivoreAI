import { BROWSER_ID } from '../../lib/browser/browser-id';

export const PAGE_TAB_PREFIX = 'page:';

export const PAGE_SLOT_PREFIX = 'terminal:pg-';

export function pageTabId(browserId: string): string {
  return PAGE_TAB_PREFIX + browserId;
}

export function pageIdOfTab(tab: string): string | null {
  if (typeof tab !== 'string' || !tab.startsWith(PAGE_TAB_PREFIX)) return null;
  const id = tab.slice(PAGE_TAB_PREFIX.length);
  return BROWSER_ID.test(id) ? id : null;
}

export function isPageTab(tab: string): boolean {
  return pageIdOfTab(tab) !== null;
}

export function isPageSlot(slot: string): boolean {
  return typeof slot === 'string' && slot.startsWith(PAGE_SLOT_PREFIX);
}

const ROW_NAME_PREFIX = 'browser:';

export function pageTabOfRowName(name: string): string | null {
  if (typeof name !== 'string' || !name.startsWith(ROW_NAME_PREFIX)) return null;
  const id = name.slice(ROW_NAME_PREFIX.length);
  return BROWSER_ID.test(id) ? pageTabId(id) : null;
}

export function pageSlotFor(tab: string, taken: readonly string[]): string | null {
  const id = pageIdOfTab(tab);
  if (id === null) return null;
  let slot = PAGE_SLOT_PREFIX + id;
  for (let n = 2; taken.includes(slot); n += 1) slot = `${PAGE_SLOT_PREFIX}${id}-${n}`;
  return slot;
}

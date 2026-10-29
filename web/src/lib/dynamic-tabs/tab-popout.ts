import { readMigrating } from '../browser-storage-migrate';
import { POPOUT_PATH, featuresFor, parseGeometry, type PopoutGeometry } from '../../popout/popout';

/* pop-out window */
export const TAB_PARAM = 'tab';

export const TAB_WINDOW_DEFAULT: Readonly<PopoutGeometry> = Object.freeze({ width: 440, height: 760 });

const TAB_ID = /^[a-z][a-z0-9-]*$/;

export function tabFromSearch(search: string): string | null {
  const id = new URLSearchParams(search).get(TAB_PARAM);
  return id && TAB_ID.test(id) ? id : null;
}

export function tabPath(id: string, params: Readonly<Record<string, string>> = {}): string {
  const query = new URLSearchParams({ [TAB_PARAM]: id, ...params });
  return `${POPOUT_PATH}?${query.toString()}`;
}

export function tabWindowName(id: string, nonce: string | null = null): string {
  return nonce ? `carnivore-tab-${id}-${nonce}` : `carnivore-tab-${id}`;
}

let opens = 0;
export function freshNonce(): string {
  opens += 1;
  return `${Date.now().toString(36)}${opens.toString(36)}`;
}

export function tabGeometryKey(id: string): string {
  return `carnivore.popout.tab.${id}.geometry`;
}

export function openTabPopout(id: string, win: Window = window, params: Readonly<Record<string, string>> = {}, multi = false): Window | null {
  if (!TAB_ID.test(id)) return null;
  const saved = readMigrating(tabGeometryKey(id));
  const geometry = saved ? parseGeometry(saved) : { ...TAB_WINDOW_DEFAULT };
  const opened = win.open(tabPath(id, params), tabWindowName(id, multi ? freshNonce() : null), featuresFor(geometry));
  opened?.focus();
  return opened;
}

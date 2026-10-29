/*  hidden  */
import { asFootBarItems, DEFAULT_FOOT_BAR_ITEMS, FOOT_BAR_ITEMS_FIELD, type FootBarItems } from './foot-plan';

interface Bridge {
  read(field: string, localReader: () => unknown): unknown;
  write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
  const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
  return found && typeof found.read === 'function' ? found : null;
}

const SAVED = new Set(['committed', 'unchanged']);

export function readFootBarItems(): FootBarItems {
  return asFootBarItems(bridge()?.read(FOOT_BAR_ITEMS_FIELD, () => DEFAULT_FOOT_BAR_ITEMS));
}

export async function saveFootBarItems(items: FootBarItems): Promise<string | null> {
  const found = bridge();
  if (!found) return 'unavailable';
  const result = (await found.write(FOOT_BAR_ITEMS_FIELD, items, () => {})) as
    { status?: string; detail?: string } | null;
  const status = result && typeof result.status === 'string' ? result.status : '';
  if (SAVED.has(status)) return null;
  return (result && result.detail) || status || 'the server did not answer';
}

export function followFootBarItems(apply: (items: FootBarItems) => void): () => void {
  const found = bridge();
  if (!found || typeof found.follow !== 'function') return () => {};
  return found.follow(FOOT_BAR_ITEMS_FIELD, (value) => apply(asFootBarItems(value)));
}

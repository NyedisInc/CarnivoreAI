
export const FOOT_BAR_ORDER_IDS = ['context', 'window_5h', 'window_7d'] as const;

export type FootBarOrderId = (typeof FOOT_BAR_ORDER_IDS)[number];

export const FOOT_BAR_ORDER_FIELD = 'foot_bar_order';

export const DEFAULT_FOOT_BAR_ORDER: readonly FootBarOrderId[] = FOOT_BAR_ORDER_IDS;

interface Bridge {
  read(field: string, localReader: () => unknown): unknown;
  write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
  const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
  return found && typeof found.read === 'function' ? found : null;
}

export function asFootBarOrder(value: unknown): FootBarOrderId[] {
  const kept: FootBarOrderId[] = [];
  if (Array.isArray(value)) {
    for (const entry of value) {
      const id = FOOT_BAR_ORDER_IDS.find((known) => known === entry);
      if (id && !kept.includes(id)) kept.push(id);
    }
  }
  for (const id of DEFAULT_FOOT_BAR_ORDER) if (!kept.includes(id)) kept.push(id);
  return kept;
}

export function moveInOrder(order: readonly FootBarOrderId[], id: FootBarOrderId, direction: 'up' | 'down'): FootBarOrderId[] {
  const at = order.indexOf(id);
  const to = direction === 'up' ? at - 1 : at + 1;
  const next = [...order];
  if (at < 0 || to < 0 || to >= next.length) return next;
  [next[at], next[to]] = [next[to] as FootBarOrderId, next[at] as FootBarOrderId];
  return next;
}

export function readFootBarOrder(): FootBarOrderId[] {
  return asFootBarOrder(bridge()?.read(FOOT_BAR_ORDER_FIELD, () => null));
}

export function followFootBarOrder(apply: (order: FootBarOrderId[]) => void): () => void {
  const found = bridge();
  if (!found || typeof found.follow !== 'function') return () => {};
  return found.follow(FOOT_BAR_ORDER_FIELD, (value) => apply(asFootBarOrder(value)));
}

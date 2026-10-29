import { preferenceField } from '../../../lib/preferences/field';

export const FOOT_BAR_ORDER_IDS = ['context', 'window_5h', 'window_7d'] as const;

export type FootBarOrderId = (typeof FOOT_BAR_ORDER_IDS)[number];

export const FOOT_BAR_ORDER_FIELD = 'foot_bar_order';

export const DEFAULT_FOOT_BAR_ORDER: readonly FootBarOrderId[] = FOOT_BAR_ORDER_IDS;

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

const field = preferenceField<FootBarOrderId[]>(FOOT_BAR_ORDER_FIELD, asFootBarOrder, [...DEFAULT_FOOT_BAR_ORDER]);

export function readFootBarOrder(): FootBarOrderId[] {
  return field.read();
}

export function followFootBarOrder(apply: (order: FootBarOrderId[]) => void): () => void {
  return field.follow(apply);
}

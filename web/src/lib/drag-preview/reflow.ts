import { moveBefore } from '../drawer-tabs/menu-order.svelte';

export interface DropSpot {
  before: string | null;
  end?: string | null;
}

export function previewOrder(order: readonly string[], id: string, spot: DropSpot | null): string[] {
  if (!spot || !order.includes(id)) return [...order];
  return moveBefore(order, id, spot.before ?? spot.end ?? null);
}

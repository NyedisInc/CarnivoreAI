/*  hidden  */
import type { HuddleItem } from './huddle-model';

export const MARKERS = ['diamond', 'square', 'triangle', 'circle', 'hexagon', 'pentagon', 'star', 'cross'] as const;

export type MarkerId = (typeof MARKERS)[number];

export const MARKER_TOKEN: Readonly<Record<MarkerId, string>> = Object.freeze({
  diamond: 'var(--oc-series-1)',
  square: 'var(--oc-series-2)',
  triangle: 'var(--oc-series-3)',
  circle: 'var(--oc-series-4)',
  hexagon: 'var(--oc-series-5)',
  pentagon: 'var(--oc-series-6)',
  star: 'var(--oc-series-7)',
  cross: 'var(--oc-series-8)',
});

export const MARKER_PATH: Readonly<Record<MarkerId, string>> = Object.freeze({
  diamond: 'M5 0L10 5L5 10L0 5Z',
  square: 'M1 1H9V9H1Z',
  triangle: 'M5 0.5L9.6 9H0.4Z',
  circle: 'M5 0.5A4.5 4.5 0 1 0 5 9.5A4.5 4.5 0 1 0 5 0.5Z',
  hexagon: 'M2.5 0.8H7.5L10 5L7.5 9.2H2.5L0 5Z',
  pentagon: 'M5 0.3L9.8 3.8L8 9.5H2L0.2 3.8Z',
  star: 'M5 0.2L6.3 3.6L9.9 3.8L7.1 6.1L8 9.7L5 7.7L2 9.7L2.9 6.1L0.1 3.8L3.7 3.6Z',
  cross: 'M3.5 0.5H6.5V3.5H9.5V6.5H6.5V9.5H3.5V6.5H0.5V3.5H3.5Z',
});

export function markerOf(item: Pick<HuddleItem, 'marker'>): MarkerId | null {
  const id = item.marker;
  return id && (MARKERS as readonly string[]).includes(id) ? (id as MarkerId) : null;
}

export function markerKey(id: MarkerId): string {
  return `cplug.huddle.marker.${id}`;
}

export function markersInUse(items: readonly Pick<HuddleItem, 'marker'>[]): { id: MarkerId; count: number }[] {
  const counts = new Map<MarkerId, number>();
  for (const item of items) {
    const id = markerOf(item);
    if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return MARKERS.filter((id) => counts.has(id)).map((id) => ({ id, count: counts.get(id) ?? 0 }));
}

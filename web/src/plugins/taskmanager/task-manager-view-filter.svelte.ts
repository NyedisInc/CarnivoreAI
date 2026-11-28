import { fuzzyMatch } from './task-manager-fuzzy';
import { markerOf, type MarkerId } from './task-manager-markers';
import type { HuddleItem } from './huddle-model';
import { statusSectionOf, type TaskManagerSectionKey } from './task-manager-status-sections';

export type ViewChip = 'needs_you' | 'unread' | 'scheduled';

export interface ViewFilter {
  query: string;
  markers: MarkerId[];
  status: TaskManagerSectionKey | null;
  chip?: ViewChip | null;
  chipTest?: ((item: HuddleItem) => boolean) | null;
}

export const viewFilter = $state<ViewFilter>({ query: '', markers: [], status: null, chip: null, chipTest: null });

function searchable(item: HuddleItem): string {
  return `${item.title ?? ''}\n${item.text}`;
}

export function matchesView(item: HuddleItem, filter: ViewFilter = viewFilter): boolean {
  if (filter.markers.length > 0) {
    const id = markerOf(item);
    if (!id || !filter.markers.includes(id)) return false;
  }
  if (filter.status !== null && statusSectionOf(item) !== filter.status) return false;
  if (filter.chip && filter.chipTest && !filter.chipTest(item)) return false;
  const query = filter.query.trim();
  return query === '' || fuzzyMatch(query, searchable(item));
}

export function viewFilterActive(filter: ViewFilter = viewFilter): boolean {
  return filter.query.trim() !== '' || filter.markers.length > 0 || filter.status !== null || !!filter.chip;
}

export function filterView(items: readonly HuddleItem[], filter: ViewFilter = viewFilter): HuddleItem[] {
  return viewFilterActive(filter) ? items.filter((item) => matchesView(item, filter)) : (items as HuddleItem[]);
}

export function setViewQuery(query: string): void {
  viewFilter.query = query;
}

export function toggleViewMarker(id: MarkerId, on: boolean): void {
  viewFilter.markers = on ? [...viewFilter.markers.filter((m) => m !== id), id] : viewFilter.markers.filter((m) => m !== id);
}

export function toggleViewStatus(key: TaskManagerSectionKey): void {
  viewFilter.status = viewFilter.status === key ? null : key;
}

export function setViewChip(chip: ViewChip | null, test: ((item: HuddleItem) => boolean) | null = null): void {
  viewFilter.chip = chip;
  viewFilter.chipTest = chip === null ? null : test;
}

export function clearViewFilter(): void {
  viewFilter.query = '';
  viewFilter.markers = [];
  viewFilter.status = null;
  viewFilter.chip = null;
  viewFilter.chipTest = null;
}

export function dropUnusedMarkers(inUse: readonly MarkerId[]): void {
  const kept = viewFilter.markers.filter((id) => inUse.includes(id));
  if (kept.length !== viewFilter.markers.length) viewFilter.markers = kept;
}

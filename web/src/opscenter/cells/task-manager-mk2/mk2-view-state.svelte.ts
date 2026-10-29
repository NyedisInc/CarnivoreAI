import { untrack } from 'svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { setViewChip, setViewQuery, viewFilter, viewFilterActive, type ViewChip } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import type { Tab } from '../../../cplugs/huddle/task-manager-design/model';
import { MK2_CHIP_TEST } from './mk2-chips';

export interface Mk2SavedView { query: string; chip: ViewChip | null; open: number | null; tab: Tab }

export const MK2_VIEW_DEFAULT: Mk2SavedView = Object.freeze({ query: '', chip: null, open: null, tab: 'action' });

export interface Mk2ViewHolder { view: Mk2SavedView | null }

const CHIPS: readonly unknown[] = ['needs_you', 'unread', 'scheduled', null];
const TABS: readonly unknown[] = ['action', 'discussion', 'details', 'subtasks'];

export function isSavedView(value: unknown): value is Mk2SavedView | null {
  if (value === null) return true;
  if (typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return typeof v['query'] === 'string' && CHIPS.includes(v['chip']) && (v['open'] === null || Number.isInteger(v['open'])) && TABS.includes(v['tab']);
}

export function useMk2View(holder: Mk2ViewHolder): void {
  const saved = holder.view;
  if (saved && !viewFilterActive() && huddle.openId === null) {
    setViewQuery(saved.query);
    setViewChip(saved.chip, saved.chip ? MK2_CHIP_TEST[saved.chip] : null);
  }
  $effect(() => {
    const query = viewFilter.query;
    const chip = viewFilter.chip ?? null;
    untrack(() => {
      const now = holder.view ?? MK2_VIEW_DEFAULT;
      if (query !== now.query || chip !== now.chip) holder.view = { ...now, query, chip };
    });
  });
}

export function saveTab(holder: Mk2ViewHolder, open: number, tab: Tab): void {
  const now = holder.view ?? MK2_VIEW_DEFAULT;
  if (now.open === open && now.tab === tab) return;
  if (now.open !== open && tab === 'action') return;
  holder.view = { ...now, open, tab };
}

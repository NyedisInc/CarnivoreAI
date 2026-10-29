import { untrack } from 'svelte';
import { authFetch } from '../sdk';
import type { HuddleItem } from './huddle-model';

export const DONE_PAGE = 50;

interface DonePage {
  items: HuddleItem[];
  total: number;
  next: number | null;
  loading: boolean;
}

export interface DoneBinding {
  extraQuery: (list: string) => string;
  repaint: (list: string, replaced: ReadonlySet<number>) => void;
}

export const doneStore = $state<{ pages: Record<string, DonePage> }>({ pages: {} });

const holds = new Map<string, number>();
let binding: DoneBinding = { extraQuery: () => '', repaint: () => undefined };
const newest = new Map<string, number>();
let stamp = 0;

export function bindDone(next: DoneBinding): void {
  binding = next;
}

export function withDone(list: string, items: HuddleItem[]): HuddleItem[] {
  const loaded = doneStore.pages[list]?.items;
  if (!loaded || loaded.length === 0) return items;
  const live = new Set(items.map((i) => i.id));
  return [...items, ...loaded.filter((i) => !live.has(i.id))];
}

export function hasMoreDone(list: string): boolean {
  return doneStore.pages[list]?.next != null;
}

export function doneLoading(list: string): boolean {
  return doneStore.pages[list]?.loading === true;
}

export function doneLeft(list: string): number {
  const page = doneStore.pages[list];
  return page ? Math.max(0, page.total - page.items.length) : 0;
}

async function readPage(list: string, offset: number, limit: number, replace: boolean): Promise<void> {
  const mine = ++stamp;
  newest.set(list, mine);
  const had = doneStore.pages[list];
  doneStore.pages[list] = { items: had?.items ?? [], total: had?.total ?? 0, next: had?.next ?? null, loading: true };
  try {
    const page = await authFetch<{ items: HuddleItem[]; total: number; next_offset: number | null }>(
      `/cplugs/huddle/lists/${encodeURIComponent(list)}/done?limit=${limit}&offset=${offset}${binding.extraQuery(list)}`);
    if (newest.get(list) !== mine) return;
    const before = new Set((doneStore.pages[list]?.items ?? []).map((i) => i.id));
    const items = replace ? page.items : [...(doneStore.pages[list]?.items ?? []), ...page.items.filter((i) => !before.has(i.id))];
    doneStore.pages[list] = { items, total: page.total, next: page.next_offset, loading: false };
    binding.repaint(list, before);
  } catch (error) {
    console.warn('huddle: could not read the done items', error);
    if (newest.get(list) === mine && doneStore.pages[list]) doneStore.pages[list].loading = false;
  }
}

export async function loadMoreDone(list: string): Promise<void> {
  const page = doneStore.pages[list];
  if (page?.loading || (page && page.next === null)) return;
  await readPage(list, page?.next ?? 0, DONE_PAGE, false);
}

export function holdDone(list: string): () => void {
  const count = holds.get(list) ?? 0;
  holds.set(list, count + 1);
  if (count === 0 && !untrack(() => doneStore.pages[list])) untrack(() => void readPage(list, 0, DONE_PAGE, true));
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const left = (holds.get(list) ?? 1) - 1;
    if (left <= 0) {
      holds.delete(list);
      const gone = new Set((doneStore.pages[list]?.items ?? []).map((i) => i.id));
      newest.delete(list);
      delete doneStore.pages[list];
      binding.repaint(list, gone);
    } else holds.set(list, left);
  };
}

export async function refreshDoneOf(list: string): Promise<void> {
  if (!holds.has(list)) return;
  await readHeld(list);
}

function readHeld(list: string): Promise<void> {
  const loaded = doneStore.pages[list]?.items.length ?? 0;
  return readPage(list, 0, Math.min(200, Math.max(DONE_PAGE, loaded)), true);
}

export async function refreshHeldDone(): Promise<void> {
  await Promise.all([...holds.keys()].map(readHeld));
}

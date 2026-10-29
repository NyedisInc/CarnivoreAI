import { authFetch } from '../../opscenter/api/auth.svelte';
import type { CardColumn, CardView } from './board-types';

export type CardAction = 'top' | 'bottom' | 'pause' | 'done' | 'promote' | 'reclassify' | 'archive' | 'collapse' | 'delete';

export function isWaiting(card: Pick<CardView, 'column' | 'queued' | 'lane_role'>): boolean {
  if (card.lane_role) return false;
  return card.column === 'todo' || (card.column === 'in_progress' && card.queued);
}

export function stageActions(card: Pick<CardView, 'column' | 'queued' | 'lane_role' | 'archived_at'>): CardAction[] {
  if (card.lane_role) return ['collapse'];
  if (card.archived_at !== null) return ['archive', 'delete'];
  const out: CardAction[] = [];
  if (isWaiting(card)) out.push('top', 'bottom');
  if (card.column === 'in_progress') out.push('pause');
  if (card.column === 'review') out.push('done');
  if (card.column === 'todo') out.push('promote');
  out.push('reclassify', 'archive', 'collapse', 'delete');
  return out;
}

export function beforeIdAt(cards: readonly CardView[], draggedId: number, index: number, listKey: string): number | null {
  for (const c of cards.slice(Math.max(0, index))) {
    if (c.id !== draggedId && c.list_key === listKey && isWaiting(c)) return c.id;
  }
  return null;
}

export function dropIsNoop(cards: readonly CardView[], draggedId: number, before: number | null): boolean {
  const at = cards.findIndex((c) => c.id === draggedId);
  const card = cards[at];
  if (!card) return false;
  return beforeIdAt(cards, draggedId, at + 1, card.list_key) === before;
}

export const dragging = $state<{ card: CardView | null }>({ card: null });

export const cardNotice = $state({ text: '', ok: true, at: 0 });

function say(text: string, ok: boolean): void {
  cardNotice.text = text;
  cardNotice.ok = ok;
  cardNotice.at = Date.now();
}

type Call = { path: string; method: 'POST' | 'DELETE'; body?: Record<string, unknown> };

export const columnCall = (id: number, column: CardColumn, note?: string): Call =>
  ({ path: `/swarm/cards/${id}/column`, method: 'POST', body: note ? { column, note } : { column } });
export const moveCall = (id: number, before: number | null): Call => ({ path: `/swarm/cards/${id}/move`, method: 'POST', body: { before_id: before } });
export const archiveCall = (id: number, on: boolean): Call => ({ path: `/swarm/cards/${id}/archive`, method: 'POST', body: { on } });
export const autoPromoteCall = (id: number, on: boolean): Call => ({ path: `/swarm/cards/${id}/auto-promote`, method: 'POST', body: { on } });
export const deleteCall = (id: number): Call => ({ path: `/swarm/cards/${id}`, method: 'DELETE' });

export async function runCalls(calls: readonly Call[], okText: string, refresh: () => Promise<void>, failText: (error: string) => string): Promise<boolean> {
  try {
    for (const call of calls) {
      await authFetch(call.path, { method: call.method, body: call.body ? JSON.stringify(call.body) : undefined });
    }
    say(okText, true);
    return true;
  } catch (failure) {
    say(failText(failure instanceof Error ? failure.message : String(failure)), false);
    return false;
  } finally {
    await refresh();
  }
}

export const COLLAPSED_KEY = 'carnivore.swarm-board.collapsed';

export function readCollapsed(): number[] {
  try {
    const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(COLLAPSED_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((n): n is number => Number.isInteger(n)) : [];
  } catch {
    return [];
  }
}

export const collapsed = $state<{ ids: number[] }>({ ids: readCollapsed() });

export function toggleCollapsed(id: number): void {
  collapsed.ids = collapsed.ids.includes(id) ? collapsed.ids.filter((n) => n !== id) : [...collapsed.ids, id];
  try {
    globalThis.localStorage?.setItem(COLLAPSED_KEY, JSON.stringify(collapsed.ids));
  } catch {
  }
}

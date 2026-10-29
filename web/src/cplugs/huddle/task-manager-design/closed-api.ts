import { ApiError, authFetch } from '../../sdk';
import { refusalCode, type HuddleItem } from '../huddle-model';
import { explain, huddle } from '../huddle.svelte';

const BASE = '/cplugs/huddle';

export interface Closure {
  id: number;
  closed_at: number | null;
  closed_by: string | null;
  outcome: 'completed' | 'cancelled';
  known: boolean;
  can_undo: boolean;
}

export interface ClosedRow {
  item: HuddleItem;
  closure: Closure;
}

export interface ClosedPage {
  items: ClosedRow[];
  next_cursor: string | null;
}

export interface Delivery {
  delivery_id: string;
  message_id: number;
  status: string;
  due_at: number | null;
  text: string;
}

export interface ClosedQuery {
  q?: string;
  cursor?: string | null;
  limit?: number;
  list?: string | null;
}

export function fetchClosed(query: ClosedQuery = {}): Promise<ClosedPage> {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.cursor) params.set('cursor', query.cursor);
  if (query.limit) params.set('limit', String(query.limit));
  if (query.list) params.set('list', query.list);
  const text = params.toString();
  return authFetch<ClosedPage>(`${BASE}/closed${text ? `?${text}` : ''}`);
}

export function undoCompletion(item: Pick<HuddleItem, 'id' | 'revision'>): Promise<{ item: HuddleItem; retraction: Delivery }> {
  return authFetch(`${BASE}/items/${item.id}/undo-completion`, { method: 'POST', body: JSON.stringify({ expected_revision: item.revision }) });
}

export function cancelTask(item: Pick<HuddleItem, 'id' | 'revision'>, note = ''): Promise<{ item: HuddleItem; notice: Delivery }> {
  return authFetch(`${BASE}/items/${item.id}/cancel`, { method: 'POST', body: JSON.stringify({ expected_revision: item.revision, ...(note.trim() ? { note: note.trim() } : {}) }) });
}

export function refusalWords(error: unknown): string {
  if (error instanceof ApiError && refusalCode(error.payload) !== null) {
    const said = (error.payload as { detail?: { detail?: unknown } }).detail?.detail;
    if (typeof said === 'string' && said) return said;
  }
  return explain(error);
}

export async function cancelWithNotice(item: Pick<HuddleItem, 'id' | 'revision'>): Promise<void> {
  try {
    await cancelTask(item);
  } catch (error) {
    huddle.notice = refusalWords(error);
  }
}

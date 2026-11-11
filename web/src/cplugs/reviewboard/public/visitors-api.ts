import { type VisitorAnswerBody, type VisitorRevision } from '../board-visitor-revisions.svelte';
import { ApiError, authFetch } from '../../sdk';

export interface VisitorEntry {
  label: string | null;
  picks?: string[];
  checked?: boolean;
  text?: string;
  note?: string;
}

export interface VisitorResponse {
  id: number;
  revision: string;
  kind: 'answers' | 'comment';
  name: string | null;
  created_at: number;
  forwarded_at: number | null;
  entries: VisitorEntry[];
}

export interface ForwardResult { forwarded: number; left: number; messages: number; message_id: number | null; item_id: number | null }

const VISITORS = '/cplugs/reviewboard/public/visitors';

export const VISITORS_TOPIC = 'cplug.reviewboard.visitors';

export function visitorsTopic(slug: string): string {
  return `${VISITORS_TOPIC}:${slug}`;
}
export const VISITORS_POLL_MS = 60_000;

export function unforwarded(rows: readonly VisitorResponse[]): number {
  return rows.filter((row) => row.forwarded_at === null).length;
}

export interface VisitorsAnswer { responses: VisitorResponse[]; visitors: VisitorRevision[]; present: number[]; viewing: number }

export async function listVisitors(board: string): Promise<VisitorsAnswer> {
  const out = await authFetch<Partial<VisitorsAnswer>>(`${VISITORS}?board=${encodeURIComponent(board)}`);
  return { responses: out.responses ?? [], visitors: out.visitors ?? [], present: out.present ?? [], viewing: out.viewing ?? 0 };
}

export function forwardVisitors(board: string, ids: number[]): Promise<ForwardResult> {
  return authFetch<ForwardResult>(`${VISITORS}/forward`, { method: 'POST', body: JSON.stringify({ board, ids }) });
}

export async function removeVisitor(id: number): Promise<void> {
  await authFetch(`${VISITORS}/${id}`, { method: 'DELETE' });
}

export async function removeForwarded(board: string): Promise<number> {
  const out = await authFetch<{ removed: number }>(`${VISITORS}?board=${encodeURIComponent(board)}`, { method: 'DELETE' });
  return out.removed;
}

function visitorPath(board: string, number: number, revision: string | null): string {
  const query = new URLSearchParams({ board, ...(revision ? { revision } : {}) });
  return `${VISITORS}/u/${number}?${query.toString()}`;
}

export async function visitorAnswers(board: string, revision: string, number: number): Promise<VisitorAnswerBody | null> {
  try {
    return (await authFetch<{ body: VisitorAnswerBody }>(visitorPath(board, number, revision))).body;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function removeVisitorRevision(board: string, number: number, revision: string | null): Promise<number> {
  return (await authFetch<{ removed: number }>(visitorPath(board, number, revision), { method: 'DELETE' })).removed;
}

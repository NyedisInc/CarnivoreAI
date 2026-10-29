import { authFetch, authFetchBlob, sendOutbox } from '../sdk';
import type { AttachmentList } from './attachment-model';
import { roundText } from './round-confirm';
import { BASE, type BoardAnswer, type BoardList, type DraftWire, type PayloadDraftAnswer, type PayloadDraftWire, type RoundAnswer, type RoundWire, type TaskChoice, type TicketAnswer } from './board-model';

export interface BoardFilter { state?: string; project?: string }

export function fetchBoards(filter: BoardFilter = {}): Promise<BoardList> {
  const query = new URLSearchParams();
  if (filter.state) query.set('state', filter.state);
  if (filter.project) query.set('project', filter.project);
  const qs = query.toString();
  return authFetch<BoardList>(`${BASE}/boards${qs ? `?${qs}` : ''}`);
}

export async function openRound(target: { slug: string; revision?: string }): Promise<void> {
  const body = target.revision ? { revision: target.revision } : {};
  await authFetch(`${BASE}/boards/${encodeURIComponent(target.slug)}/open`, { method: 'POST', body: JSON.stringify(body) });
}

export function fetchBoard(slug: string): Promise<BoardAnswer> {
  return authFetch<BoardAnswer>(`${BASE}/boards/${encodeURIComponent(slug)}`);
}

export function fetchAttachments(slug: string): Promise<AttachmentList> {
  return authFetch<AttachmentList>(`${BASE}/boards/${encodeURIComponent(slug)}/attachments`);
}

export function fetchAttachmentBlob(path: string): Promise<Blob> {
  return authFetchBlob(path);
}

export function mintTicket(slug: string, revision: string, view: string): Promise<TicketAnswer> {
  return authFetch<TicketAnswer>(`${BASE}/boards/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revision)}/ticket`, {
    method: 'POST', body: JSON.stringify({ view }),
  });
}

export function rescan(): Promise<BoardList> {
  return authFetch<BoardList>(`${BASE}/rescan`, { method: 'POST' });
}

export async function fetchDraft(slug: string): Promise<DraftWire | null> {
  return (await authFetch<{ draft: DraftWire | null }>(`${BASE}/boards/${encodeURIComponent(slug)}/draft`)).draft;
}

export async function saveDraft(slug: string, body: DraftWire): Promise<DraftWire> {
  return (await authFetch<{ draft: DraftWire }>(`${BASE}/boards/${encodeURIComponent(slug)}/draft`, { method: 'PUT', body: JSON.stringify(body) })).draft;
}

export async function deleteDraft(slug: string): Promise<void> {
  await authFetch<unknown>(`${BASE}/boards/${encodeURIComponent(slug)}/draft`, { method: 'DELETE' });
}

/* did not answer */
export async function sendRoundKept(slug: string, body: RoundWire, where: string, item: number): Promise<RoundAnswer | 'kept'> {
  const out = await sendOutbox({
    id: body.client_round_id,
    kind: 'round',
    request: { method: 'POST', path: `${BASE}/boards/${encodeURIComponent(slug)}/rounds`, body: body as unknown as Record<string, unknown> },
    ageField: null,
    after: null,
    label: { text: roundText(body), where, list: null, item: item || null, slug },
  });
  if (out.ok) return out.answer as RoundAnswer;
  if (out.kept) return 'kept';
  throw out.cause;
}

export function savePayloadDraft(slug: string, body: PayloadDraftWire, keepalive = false): Promise<PayloadDraftAnswer> {
  return authFetch<PayloadDraftAnswer>(`${BASE}/boards/${encodeURIComponent(slug)}/payload-draft`, { method: 'PUT', body: JSON.stringify(body), keepalive });
}

export function resendRound(slug: string, round: string): Promise<RoundAnswer> {
  return authFetch<RoundAnswer>(`${BASE}/boards/${encodeURIComponent(slug)}/rounds/${encodeURIComponent(round)}/resend`, { method: 'POST', body: '{}' });
}

export function relinkTask(slug: string, itemId: number): Promise<unknown> {
  return authFetch<unknown>(`${BASE}/boards/${encodeURIComponent(slug)}/task`, { method: 'PATCH', body: JSON.stringify({ item_id: itemId }) });
}

export async function fetchTasks(list: string): Promise<TaskChoice[]> {
  const body = await authFetch<{ items?: Array<{ id: number; title?: string | null; text?: string; status?: string }> }>(`/cplugs/huddle/lists/${encodeURIComponent(list)}`);
  return (body.items ?? []).map((i) => ({ id: i.id, title: (i.title || (i.text ?? '').split('\n')[0] || `item ${i.id}`).slice(0, 120), status: i.status ?? '' }));
}

export interface ScratchCleared { slug: string; revisions: number; files: number; bytes: number }

export function clearScratch(slug: string): Promise<ScratchCleared> {
  return authFetch<ScratchCleared>(`${BASE}/boards/${encodeURIComponent(slug)}`, { method: 'DELETE' });
}

export interface MilestoneAnswer { slug: string; etag: string; state: string; revision: string | null; milestone: string | null; unchanged: boolean; card: { posted: boolean } }
export interface LiveSendAnswer { send: { n: number }; etag: string; delivery: { state: string; via?: string | null; reason?: string | null }; state: string; duplicate: boolean; tell?: string | null }

export function bookmarkDraft(slug: string, name: string): Promise<MilestoneAnswer> {
  const trimmed = name.trim();
  return authFetch<MilestoneAnswer>(`${BASE}/boards/${encodeURIComponent(slug)}/live/milestone`, { method: 'POST', body: JSON.stringify(trimmed ? { name: trimmed } : {}) });
}

export function endLive(slug: string): Promise<unknown> {
  return authFetch<unknown>(`${BASE}/boards/${encodeURIComponent(slug)}/live/end`, { method: 'POST', body: '{}' });
}

export async function sendLiveKept(slug: string, body: RoundWire, where: string, item: number): Promise<LiveSendAnswer | 'kept'> {
  const out = await sendOutbox({
    id: body.client_round_id,
    kind: 'round',
    request: { method: 'POST', path: `${BASE}/boards/${encodeURIComponent(slug)}/live/send`, body: body as unknown as Record<string, unknown> },
    ageField: null,
    after: null,
    label: { text: roundText(body), where, list: null, item: item || null, slug },
  });
  if (out.ok) return out.answer as LiveSendAnswer;
  if (out.kept) return 'kept';
  throw out.cause;
}

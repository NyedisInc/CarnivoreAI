import { authFetch } from '../../opscenter/api/auth.svelte';

export interface Bookmark {
  id: number;
  session_uuid: string;
  session_row_id: number | null;
  claude_session_uuid: string;
  entry_uuid: string;
  label: string;
  created_by: 'owner' | 'claude';
  created_at: string;
  snippet: string;
  entry_timestamp: string;
}

export interface SessionBookmark extends Bookmark {
  session_label: string;
  session_tmux: string;
  family: string;
}

export interface AllBookmarks {
  bookmarks: SessionBookmark[];
}

export interface BookmarkList {
  session_uuid: string;
  conversation: string | null;
  family: string;
  bookmarks: Bookmark[];
}

export interface Turn {
  entry_uuid: string;
  snippet: string;
  timestamp: string;
  number: number;
}

export interface TurnPage {
  session_uuid: string;
  conversation: string;
  total: number;
  turns: Turn[];
}

export interface PreviewPart {
  entry_uuid: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: string;
  truncated: boolean;
}

export interface BookmarkPreview {
  bookmark_id: number;
  conversation: string;
  turns: number;
  parts: PreviewPart[];
}

export interface BranchResult {
  session: { id?: string };
  claude_session_uuid: string;
  label: string;
  parent_session_id: number;
  lineage_recorded: boolean;
}

export interface RewindResult {
  claude_session_uuid: string;
  previous_claude_session_uuid: string;
  killed_live_pane: boolean;
  resumed_copy: boolean;
  identity_status: string | null;
  ok: boolean;
  detail: string | null;
}

export type Point = { bookmarkId: number } | { entryUuid: string };

export const TURNS_PAGE = 50;

export function bookmarksTopic(rowId: number): string {
  return `bookmarks:${rowId}`;
}

export const ALL_BOOKMARKS_TOPIC = 'bookmarks:*';

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export function listBookmarks(rowId: number): Promise<BookmarkList> {
  return authFetch<BookmarkList>(`/sessions/${rowId}/bookmarks`);
}

export function addBookmark(rowId: number, entryUuid?: string, label = ''): Promise<Bookmark> {
  return authFetch<Bookmark>(`/sessions/${rowId}/bookmarks`, json({ label, entry_uuid: entryUuid ?? null }));
}

export function deleteBookmark(id: number): Promise<Bookmark> {
  return authFetch<Bookmark>(`/bookmarks/${id}`, { method: 'DELETE' });
}

export function listTurns(rowId: number, offset = 0): Promise<TurnPage> {
  return authFetch<TurnPage>(`/sessions/${rowId}/turns?offset=${offset}&limit=${TURNS_PAGE}`);
}

export function branchFrom(rowId: number, point: Point): Promise<BranchResult> {
  return 'bookmarkId' in point
    ? authFetch<BranchResult>(`/bookmarks/${point.bookmarkId}/branch`, json({}))
    : authFetch<BranchResult>(`/sessions/${rowId}/branch`, json({ entry_uuid: point.entryUuid }));
}

export function rewindTo(rowId: number, point: Point, confirm: boolean): Promise<RewindResult> {
  return 'bookmarkId' in point
    ? authFetch<RewindResult>(`/bookmarks/${point.bookmarkId}/rewind`, json({ confirm }))
    : authFetch<RewindResult>(`/sessions/${rowId}/rewind`, json({ entry_uuid: point.entryUuid, confirm }));
}

export function getPreview(id: number, turns?: number): Promise<BookmarkPreview> {
  return authFetch<BookmarkPreview>(`/bookmarks/${id}/preview${turns === undefined ? '' : `?turns=${turns}`}`);
}

import { authFetch } from '../../api/auth.svelte';
import type { PreviewPart } from '../../../lib/bookmarks/api';

export const SAVE_PLUGIN_ROUTE = '/cplugs/save';

export interface TimelinePeek {
  conversation: string;
  entry_uuid: string;
  turns: number;
  parts: PreviewPart[];
}

export function getPeek(rowId: number, conversation: string, entryUuid: string, turns?: number): Promise<TimelinePeek> {
  const query = new URLSearchParams({ conversation, entry_uuid: entryUuid });
  if (turns !== undefined) query.set('turns', String(turns));
  return authFetch<TimelinePeek>(`/sessions/${rowId}/timeline/peek?${query.toString()}`);
}

export interface RestoreAnswer {
  transcript_status: string;
  session: { status: string; detail: string };
}

export function restorePointPath(conversation: string, pointId: string): string {
  return `${SAVE_PLUGIN_ROUTE}/conversations/${encodeURIComponent(conversation)}/points/${encodeURIComponent(pointId)}/restore`;
}

export function openRestorePoint(conversation: string, pointId: string): Promise<RestoreAnswer> {
  return authFetch<RestoreAnswer>(restorePointPath(conversation, pointId), { method: 'POST', body: JSON.stringify({}) });
}

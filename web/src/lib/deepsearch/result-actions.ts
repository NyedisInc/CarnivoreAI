import { authFetch } from '../../opscenter/api/auth.svelte';
import { readBranched, type BranchedSession } from './context-api';
import { linkHash, type ContextLink } from './context-link';

export async function resumeSession(sessionUuid: string): Promise<void> {
  await authFetch<unknown>(`/sessions/${encodeURIComponent(sessionUuid)}/restart`, { method: 'POST', body: '{}' });
}

export async function branchAt(sessionUuid: string, entryUuid: string, conversationId: string): Promise<BranchedSession> {
  const body = JSON.stringify({ entry_uuid: entryUuid, conversation: conversationId });
  return readBranched(await authFetch<unknown>(`/sessions/${encodeURIComponent(sessionUuid)}/branch`, { method: 'POST', body }));
}

export async function bookmarkAt(sessionUuid: string, entryUuid: string): Promise<void> {
  await authFetch<unknown>(`/sessions/${encodeURIComponent(sessionUuid)}/bookmarks`, { method: 'POST', body: JSON.stringify({ entry_uuid: entryUuid }) });
}

export function linkUrl(link: ContextLink, page: Pick<Location, 'origin' | 'pathname' | 'search'> = window.location): string {
  return `${page.origin}${page.pathname}${page.search}${linkHash(link)}`;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.warn('DeepSearch: the link could not be copied', err);
    return false;
  }
}

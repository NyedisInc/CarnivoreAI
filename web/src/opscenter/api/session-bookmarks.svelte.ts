import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { sharedResources } from './shared-resource';
import { ALL_BOOKMARKS_TOPIC, bookmarksTopic, type AllBookmarks, type BookmarkList } from '../../lib/bookmarks/api';

export const BOOKMARKS_POLL_MS = 30000;

const reads = sharedResources<string, unknown>();

function hold<T>(key: string, path: string, topic: string): Resource<T> {
  return reads.hold(key, () => resource<unknown>(() => authFetch<T>(path), {
    intervalMs: BOOKMARKS_POLL_MS,
    topics: [topic],
    name: `session-bookmarks:${key}`,
  })) as Resource<T>;
}

function drop(key: string): void {
  reads.drop(key);
}

export function sessionBookmarks(rowId: number): Resource<BookmarkList> {
  return hold<BookmarkList>(`s:${rowId}`, `/sessions/${rowId}/bookmarks`, bookmarksTopic(rowId));
}

export function releaseSessionBookmarks(rowId: number): void {
  drop(`s:${rowId}`);
}

export function allBookmarks(): Resource<AllBookmarks> {
  return hold<AllBookmarks>('all', '/bookmarks', ALL_BOOKMARKS_TOPIC);
}

export function releaseAllBookmarks(): void {
  drop('all');
}

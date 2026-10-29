import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { ALL_BOOKMARKS_TOPIC, bookmarksTopic, type AllBookmarks, type BookmarkList } from '../../lib/bookmarks/api';

export const BOOKMARKS_POLL_MS = 30000;

const cache = new Map<string, { resource: Resource<unknown>; refs: number }>();

function hold<T>(key: string, path: string, topic: string): Resource<T> {
  let entry = cache.get(key);
  if (!entry) {
    entry = {
      resource: resource<T>(() => authFetch<T>(path), { intervalMs: BOOKMARKS_POLL_MS, topics: [topic], name: `session-bookmarks:${key}` }),
      refs: 0,
    };
    cache.set(key, entry);
  }
  entry.refs += 1;
  return entry.resource as Resource<T>;
}

function drop(key: string): void {
  const entry = cache.get(key);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.resource.stop();
    cache.delete(key);
  }
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

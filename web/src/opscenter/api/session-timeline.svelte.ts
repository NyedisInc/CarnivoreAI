import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { bookmarksTopic } from '../../lib/bookmarks/api';
import type { SessionTimeline } from '../cells/timeline/types';

export const SESSION_TIMELINE_TOPIC = 'session_timeline';

export const SESSION_TIMELINE_POLL_MS = 30000;

const cache = new Map<number, { resource: Resource<SessionTimeline>; refs: number }>();

export function sessionTimeline(rowId: number): Resource<SessionTimeline> {
  let entry = cache.get(rowId);
  if (!entry) {
    entry = {
      resource: resource<SessionTimeline>(() => authFetch<SessionTimeline>(`/sessions/${rowId}/timeline`), {
        intervalMs: SESSION_TIMELINE_POLL_MS,
        topics: [SESSION_TIMELINE_TOPIC, bookmarksTopic(rowId)],
        name: `session-timeline:${rowId}`,
      }),
      refs: 0,
    };
    cache.set(rowId, entry);
  }
  entry.refs += 1;
  return entry.resource;
}

export function releaseSessionTimeline(rowId: number): void {
  const entry = cache.get(rowId);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.resource.stop();
    cache.delete(rowId);
  }
}

import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { sharedResources } from './shared-resource';
import { bookmarksTopic } from '../../lib/bookmarks/api';
import type { SessionTimeline } from '../cells/timeline/types';

export const SESSION_TIMELINE_TOPIC = 'session_timeline';

export const SESSION_TIMELINE_POLL_MS = 30000;

const reads = sharedResources<number, SessionTimeline>();

export function sessionTimeline(rowId: number): Resource<SessionTimeline> {
  return reads.hold(rowId, () => resource<SessionTimeline>(() => authFetch<SessionTimeline>(`/sessions/${rowId}/timeline`), {
    intervalMs: SESSION_TIMELINE_POLL_MS,
    topics: [SESSION_TIMELINE_TOPIC, bookmarksTopic(rowId)],
    name: `session-timeline:${rowId}`,
  }));
}

export function releaseSessionTimeline(rowId: number): void {
  reads.drop(rowId);
}

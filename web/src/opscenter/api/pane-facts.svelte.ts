import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { SessionPaneFacts } from './types';

export const PANE_FACTS_POLL_MS = 5000;

const cache = new Map<string, { resource: Resource<SessionPaneFacts>; refs: number }>();

export function paneFacts(sessionId: string): Resource<SessionPaneFacts> {
  let entry = cache.get(sessionId);
  if (!entry) {
    const id = encodeURIComponent(sessionId);
    entry = {
      resource: resource<SessionPaneFacts>(() => authFetch<SessionPaneFacts>(`/sessions/${id}/pane-facts`), {
        intervalMs: PANE_FACTS_POLL_MS,
        topics: [`pane_facts:${sessionId}`],
        name: `pane-facts:${sessionId}`,
      }),
      refs: 0,
    };
    cache.set(sessionId, entry);
  }
  entry.refs += 1;
  return entry.resource;
}

export function releasePaneFacts(sessionId: string): void {
  const entry = cache.get(sessionId);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.resource.stop();
    cache.delete(sessionId);
  }
}

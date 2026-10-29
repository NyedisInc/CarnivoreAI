import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { sharedResources } from './shared-resource';
import type { SessionPaneFacts } from './types';

export const PANE_FACTS_POLL_MS = 5000;

const reads = sharedResources<string, SessionPaneFacts>();

export function paneFacts(sessionId: string): Resource<SessionPaneFacts> {
  return reads.hold(sessionId, () => {
    const id = encodeURIComponent(sessionId);
    return resource<SessionPaneFacts>(() => authFetch<SessionPaneFacts>(`/sessions/${id}/pane-facts`), {
      intervalMs: PANE_FACTS_POLL_MS,
      topics: [`pane_facts:${sessionId}`],
      name: `pane-facts:${sessionId}`,
    });
  });
}

export function releasePaneFacts(sessionId: string): void {
  reads.drop(sessionId);
}

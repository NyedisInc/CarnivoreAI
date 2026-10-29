import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import type { SessionGitStatus } from './types';

export const SESSION_GIT_POLL_MS = 10000;

const cache = new Map<string, { resource: Resource<SessionGitStatus>; refs: number }>();

export function sessionGit(sessionId: string): Resource<SessionGitStatus> {
  let entry = cache.get(sessionId);
  if (!entry) {
    const id = encodeURIComponent(sessionId);
    entry = {
      resource: resource<SessionGitStatus>(() => authFetch<SessionGitStatus>(`/sessions/${id}/git-status`), {
        intervalMs: SESSION_GIT_POLL_MS,
        topics: [`git_status:${sessionId}`],
        name: `session-git:${sessionId}`,
      }),
      refs: 0,
    };
    cache.set(sessionId, entry);
  }
  entry.refs += 1;
  return entry.resource;
}

export function releaseSessionGit(sessionId: string): void {
  const entry = cache.get(sessionId);
  if (!entry) return;
  entry.refs -= 1;
  if (entry.refs <= 0) {
    entry.resource.stop();
    cache.delete(sessionId);
  }
}

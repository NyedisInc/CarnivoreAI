import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { sharedResources } from './shared-resource';
import type { SessionGitStatus } from './types';

export const SESSION_GIT_POLL_MS = 10000;

const reads = sharedResources<string, SessionGitStatus>();

export function sessionGit(sessionId: string): Resource<SessionGitStatus> {
  return reads.hold(sessionId, () => {
    const id = encodeURIComponent(sessionId);
    return resource<SessionGitStatus>(() => authFetch<SessionGitStatus>(`/sessions/${id}/git-status`), {
      intervalMs: SESSION_GIT_POLL_MS,
      topics: [`git_status:${sessionId}`],
      name: `session-git:${sessionId}`,
    });
  });
}

export function releaseSessionGit(sessionId: string): void {
  reads.drop(sessionId);
}

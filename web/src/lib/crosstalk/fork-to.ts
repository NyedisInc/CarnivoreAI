import { authFetch } from '../../opscenter/api/auth.svelte';

export interface ForkToRequest {
  provider: 'claude' | 'codex';
  model: string;
  effort: string;
  prompt: string;
  name: string;
  worktree: boolean;
}

export function forkToBody(request: ForkToRequest): Record<string, unknown> {
  const { provider, model, effort, prompt, name, worktree } = request;
  return {
    to_provider: provider,
    ...(model.trim() ? { model: model.trim() } : {}),
    ...(effort ? { effort } : {}),
    ...(prompt.trim() ? { prompt: prompt.trim() } : {}),
    ...(name.trim() ? { name: name.trim() } : {}),
    worktree,
  };
}

export async function forkSessionTo(sessionId: string, request: ForkToRequest): Promise<void> {
  await authFetch(`/sessions/${encodeURIComponent(sessionId)}/fork-to`, { method: 'POST', body: JSON.stringify(forkToBody(request)) });
}

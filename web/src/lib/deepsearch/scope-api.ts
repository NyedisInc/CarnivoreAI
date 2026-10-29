import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export const INDEX_SCOPES = ['human', 'human+subsessions', 'all'] as const;

export type IndexScope = (typeof INDEX_SCOPES)[number];

export const DEFAULT_SCOPE: IndexScope = 'all';

export const SCOPE_PATH = '/deepsearch/settings';

export function asScope(value: unknown): IndexScope {
  return INDEX_SCOPES.find((s) => s === value) ?? DEFAULT_SCOPE;
}

export function scopeKey(scope: IndexScope): string {
  return `settings.deepsearch_scope.${scope.replace('+', '_')}`;
}

export async function fetchScope(signal?: AbortSignal): Promise<IndexScope> {
  const body = await authFetch<{ indexScope?: unknown }>(SCOPE_PATH, { signal });
  return asScope(body?.indexScope);
}

export async function saveScope(scope: IndexScope): Promise<string | null> {
  try {
    await authFetch(SCOPE_PATH, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ indexScope: scope }) });
    return null;
  } catch (error) {
    if (error instanceof ApiError) return error.message;
    throw error;
  }
}

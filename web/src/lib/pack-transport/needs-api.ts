import { authFetch } from '../../opscenter/api/auth.svelte';

export interface NeedsKind {
  needs: string[];
  prefer: string[];
  stored: boolean;
  default_filters: string[];
  default_prefer: string[];
}

export interface NeedsView {
  kinds: Record<string, NeedsKind>;
  vocabulary: string[];
}

export type NeedsBody = Record<string, { needs: string[]; prefer: string[] } | null>;

export interface NeedsApi {
  read(name: string): Promise<NeedsView>;
  write(name: string, body: NeedsBody): Promise<unknown>;
}

const path = (name: string): string => `/projects/${encodeURIComponent(name)}/delegate-needs`;

export const needsApi: NeedsApi = {
  read: (name) => authFetch<NeedsView>(path(name), { method: 'GET' }),
  write: (name, body) => authFetch<unknown>(path(name), { method: 'PUT', body: JSON.stringify(body) }),
};

import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface ApiKey {
    readonly id: string;
    readonly name: string;
    readonly display_prefix: string;
    readonly created_at: number;
    readonly last_used_at: number | null;
    readonly revoked_at: number | null;
}

export async function fetchKeys(fetcher: Fetcher = authFetch): Promise<ApiKey[]> {
    const body = await fetcher<{ keys?: ApiKey[] }>('/api-keys');
    if (!Array.isArray(body?.keys)) throw new Error('unexpected api keys response');
    return body.keys;
}

export const createKey = (name: string, fetcher: Fetcher = authFetch): Promise<{ key: ApiKey; secret: string }> =>
    fetcher('/api-keys', { method: 'POST', body: JSON.stringify({ name }) });

export const revokeKey = (id: string, fetcher: Fetcher = authFetch): Promise<unknown> =>
    fetcher(`/api-keys/${encodeURIComponent(id)}`, { method: 'DELETE' });

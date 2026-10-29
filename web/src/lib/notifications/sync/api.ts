import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type LastResult = 'ok' | 'no_change' | 'off' | 'older' | 'disconnected' | 'refused' | 'rate_limited' | 'error';

export interface SyncPeer {
    readonly key: string;
    readonly label: string;
    readonly enabled: boolean;
    readonly protocol: 'ok' | 'older' | 'unknown';
    readonly connected: boolean;
    readonly last_exchange_at: number | null;
    readonly last_result: LastResult | null;
}

export interface SyncBody {
    readonly available: boolean;
    readonly peers: readonly SyncPeer[];
}

export const EMPTY_SYNC: SyncBody = { available: false, peers: [] };

const BASE = '/notifications/sync';

export async function fetchSync(fetcher: Fetcher = authFetch): Promise<SyncBody> {
    const body = await fetcher<Partial<SyncBody> | null>(BASE);
    return { available: body?.available === true, peers: Array.isArray(body?.peers) ? body.peers : [] };
}

export async function putPeer(key: string, enabled: boolean, fetcher: Fetcher = authFetch): Promise<SyncBody> {
    const body = await fetcher<Partial<SyncBody> | null>(`${BASE}/peers/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify({ enabled }) });
    return { available: body?.available === true, peers: Array.isArray(body?.peers) ? body.peers : [] };
}

export const postSyncNow = (fetcher: Fetcher = authFetch) => fetcher<{ started: boolean }>(`${BASE}/now`, { method: 'POST' });

import { authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export interface Maintenance {
    enabled: boolean;
    revision: number;
    db_bytes: number;
    clear: { state: 'idle' | 'running' | 'done' | 'failed'; phase: string; bytes_before: number | null;
        bytes_after: number | null; reclaimed_bytes: number | null; error: string };
    backfill: { state: 'idle' | 'requested' | 'running'; pending_sources: number; known_sources: number };
}

export async function fetchMaintenance(fetcher: Fetcher = authFetch): Promise<Maintenance> {
    const body = await fetcher<Maintenance>('/stats/maintenance');
    if (!body || !body.clear || !body.backfill) throw new Error('unexpected stats maintenance response');
    return body;
}

export function setStatsEnabled(enabled: boolean, revision: number, fetcher: Fetcher = authFetch): Promise<unknown> {
    return fetcher('/stats/settings', { method: 'PATCH', body: JSON.stringify({ enabled, revision }) });
}

export function startClear(fetcher: Fetcher = authFetch): Promise<unknown> {
    return fetcher('/stats/clear', { method: 'POST', body: JSON.stringify({ confirm: true }) });
}

export function startBackfill(fetcher: Fetcher = authFetch): Promise<unknown> {
    const key = `panel-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    return fetcher('/stats/backfill', { method: 'POST', body: JSON.stringify({ idempotency_key: key }) });
}

export function sizeText(bytes: number): string {
    const units = ['b', 'kb', 'mb', 'gb'];
    let value = bytes;
    let at = 0;
    while (value >= 1024 && at < units.length - 1) { value /= 1024; at += 1; }
    return at === 0 ? `${value} b` : `${value.toFixed(1)} ${units[at]}`;
}

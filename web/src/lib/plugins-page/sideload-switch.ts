import { authFetch } from '../../opscenter/api/auth.svelte';

export interface SideloadStatus {
    enabled: boolean;
    expires_at: number | null;
    items: { id: string; item_id: string; source: string; synced_at: number | null; changed: string[] }[];
}

export function loadSideload(fetcher: typeof authFetch = authFetch): Promise<SideloadStatus> {
    return fetcher<SideloadStatus>('/cplug-owner/sideload');
}

export function saveSideload(enabled: boolean, fetcher: typeof authFetch = authFetch): Promise<SideloadStatus> {
    return fetcher<SideloadStatus>('/cplug-owner/sideload/switch', { method: 'PUT', body: JSON.stringify({ enabled }) });
}


import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { repaintDrawer } from './drawer-repaint';

export interface BrowserInfo {
    id: string;
    label: string;
    url: string;
    state: 'live' | 'stopped';
    viewers: number;
    created_at: string;
    updated_at: string;
}

export const BROWSERS_POLL_MS = 5000;

export { BROWSER_ID } from './browser-id';

export const browsers: Resource<BrowserInfo[]> = resource<BrowserInfo[]>(
    async () => (await authFetch<{ browsers: BrowserInfo[] }>('/browsers')).browsers,
    {
        intervalMs: BROWSERS_POLL_MS, name: 'browsers', demo: () => [],
        topics: ['browsers'], afterPush: () => repaintDrawer(),
    },
);

export function browserById(id: string): BrowserInfo | null {
    return (browsers.data ?? []).find((b) => b.id === id) ?? null;
}

async function write<T>(path: string, init: RequestInit): Promise<T> {
    const value = await authFetch<T>(path, init);
    await browsers.refresh(true);
    repaintDrawer();
    return value;
}

export function createBrowser(url = ''): Promise<BrowserInfo> {
    return write<BrowserInfo>('/browsers', { method: 'POST', body: JSON.stringify(url ? { url } : {}) });
}

export function renameBrowser(id: string, label: string): Promise<BrowserInfo> {
    return write<BrowserInfo>(`/browsers/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ label }),
    });
}

export function closeBrowser(id: string): Promise<void> {
    return write<void>(`/browsers/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

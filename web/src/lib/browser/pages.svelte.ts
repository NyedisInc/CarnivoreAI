import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { repaintDrawer } from './drawer-repaint';
import type { PageInfo } from './page-frame';

export const BROWSER_PAGES_TOPIC = 'browser_pages';

export const PAGES_POLL_MS = 5000;

export const openPages: Resource<PageInfo[]> = resource<PageInfo[]>(
    async () => (await authFetch<{ pages: PageInfo[] }>('/browsers/pages')).pages,
    {
        intervalMs: PAGES_POLL_MS, name: 'browser_pages', demo: () => [],
        topics: [BROWSER_PAGES_TOPIC], afterPush: () => repaintDrawer(),
    },
);

export function pageById(id: string): PageInfo | null {
    return (openPages.data ?? []).find((p) => p.id === id) ?? null;
}

export async function closePage(id: string): Promise<void> {
    await authFetch<void>(`/browsers/pages/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await openPages.refresh(true);
    repaintDrawer();
}

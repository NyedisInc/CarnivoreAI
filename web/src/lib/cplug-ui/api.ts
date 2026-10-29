import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { Action } from './validate';

export type Surface = 'settings' | 'glance';

export interface SurfaceAnswer {
    surface: string;
    /* could not */
    stale: boolean;
    reason?: string;
    document: unknown;
}

export function errorCode(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const detail = (error.payload as { detail?: { code?: unknown } } | null)?.detail;
    return error.code ?? (typeof detail?.code === 'string' ? detail.code : null);
}

export function fetchSurface(cplugId: string, surface: Surface, fetcher: typeof authFetch = authFetch): Promise<SurfaceAnswer> {
    return fetcher<SurfaceAnswer>(`/cplugs/${encodeURIComponent(cplugId)}/ui/${surface}`);
}

export async function runAction(cplugId: string, action: Action, fetcher: typeof authFetch = authFetch): Promise<void> {
    if (action.call !== 'route') throw new ApiError('tool actions are not available from the page', 0, 'tool_action_unavailable');
    await fetcher(`/cplugs/${encodeURIComponent(cplugId)}/r/${encodeURIComponent(action.route)}`, {
        method: 'POST',
        body: JSON.stringify(action.payload ?? {}),
    });
}

export interface ViewTicket {
    path: string;
    expires_in: number;
}

export function fetchViewTicket(cplugId: string, view: string, fetcher: typeof authFetch = authFetch): Promise<ViewTicket> {
    return fetcher<ViewTicket>(`/cplugs/${encodeURIComponent(cplugId)}/view/${encodeURIComponent(view)}/ticket`, { method: 'POST' });
}

export function callViewRoute(cplugId: string, route: string, payload: unknown, fetcher: typeof authFetch = authFetch): Promise<unknown> {
    return fetcher(`/cplugs/${encodeURIComponent(cplugId)}/r/${encodeURIComponent(route)}`, { method: 'POST', body: JSON.stringify(payload ?? {}) });
}

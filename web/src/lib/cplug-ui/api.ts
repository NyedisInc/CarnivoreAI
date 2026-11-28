import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { CplugSlotsResponse, SlotContribution } from '../plugins/types';
import type { Action } from './validate';

export type { CplugSlotsResponse, SlotContribution };

export type Surface = 'settings' | 'glance';

export interface SurfaceAnswer {
    surface: string;
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
    if (action.call === 'tool') {
        await callViewTool(cplugId, action.name, action.payload ?? {}, fetcher);
        return;
    }
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

export function callViewTool(
    cplugId: string,
    tool: string,
    args: unknown,
    fetcher: typeof authFetch = authFetch,
    sessionRef?: string | null,
): Promise<unknown> {
    return fetcher('/cplug-owner/tool', {
        method: 'POST',
        body: JSON.stringify({
            cplug_id: cplugId,
            tool,
            args: args ?? {},
            ...(typeof sessionRef === 'string' && sessionRef.length > 0 ? { session_ref: sessionRef } : {}),
        }),
    });
}

export function callOwnerAct(
    cplugId: string,
    routeOrMacro: string,
    payload?: unknown,
    sessionRef?: string | null,
    fetcher: typeof authFetch = authFetch,
): Promise<unknown> {
    return fetcher('/cplug-owner/act', {
        method: 'POST',
        body: JSON.stringify({
            cplug_id: cplugId,
            route: routeOrMacro,
            ...(typeof sessionRef === 'string' && sessionRef.length > 0 ? { session_ref: sessionRef } : {}),
            ...(payload !== undefined ? { body: payload } : {}),
        }),
    });
}

export function fetchSlots(fetcher: typeof authFetch = authFetch): Promise<CplugSlotsResponse> {
    return fetcher<CplugSlotsResponse>('/cplugs/slots');
}

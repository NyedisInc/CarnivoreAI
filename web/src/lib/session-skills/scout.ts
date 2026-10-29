import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export interface ScoutSuggestion {
    item_id: string;
    name: string;
    reason: string;
}

export interface ScoutReply {
    state: 'none' | 'waiting' | 'ready' | 'not_measured' | 'unsupported';
    suggestions: ScoutSuggestion[];
    detail?: string | null;
}

const base = (sessionId: string): string => `/sessions/${encodeURIComponent(sessionId)}/skills/scout`;

export function fetchScout(sessionId: string): Promise<ScoutReply> {
    return authFetch<ScoutReply>(base(sessionId));
}

export function requestScout(sessionId: string): Promise<{ pasted_bytes: number; items_listed: number }> {
    return authFetch(base(sessionId), { method: 'POST' });
}

export function scoutRefusal(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        const detail = (error.payload as { detail?: unknown } | null)?.detail;
        if (detail && typeof detail === 'object') {
            const message = (detail as { message?: unknown }).message;
            if (typeof message === 'string' && message.trim() !== '') return message;
        }
    }
    return fallback;
}

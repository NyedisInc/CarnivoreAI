import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import { clipChars } from '../catalog/bounds';
import type { SubEvent, SubRow } from './types';

export const MAX_ROWS = 2000;
export const MAX_EVENTS = 40;
const SHORT = 120;
const LONG = 400;

export function text(value: unknown, limit = SHORT): string {
    return typeof value === 'string' ? (clipChars(value, limit) ?? '') : '';
}

export function num(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function bag(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function parseEvent(raw: unknown): SubEvent | null {
    const row = bag(raw);
    const what = text(row.what, 40);
    if (!what) return null;
    const event: SubEvent = { at: text(row.at, 40), what };
    for (const field of ['reason', 'text', 'version'] as const) {
        const value = text(row[field], field === 'version' ? 40 : LONG);
        if (value) event[field] = value;
    }
    return event;
}

export function parseMineRow(raw: unknown): SubRow | null {
    const row = bag(raw);
    const id = text(row.submission_id, 64);
    if (!id) return null;
    return {
        id,
        status: text(row.status, 40),
        gate_state: text(row.gate_state, 40),
        item_id: text(row.item_id),
        kind: text(row.kind, 20),
        name: text(row.name),
        version: text(row.version, 40),
        new_version: row.new_version === true,
        media_only: row.media_only === true,
        reason: text(row.reason, LONG),
        appeals_left: num(row.appeals_left),
        created_at: text(row.created_at, 40),
        decided_at: text(row.decided_at, 40),
        published_at: text(row.published_at, 40),
        revoked_at: text(row.revoked_at, 40),
        revocation_reason: text(row.revocation_reason, LONG),
        events: (Array.isArray(row.events) ? row.events : []).slice(-MAX_EVENTS).map(parseEvent).filter((e): e is SubEvent => e !== null),
    };
}

export function parseMine(body: unknown): SubRow[] {
    const list = bag(body).submissions;
    return (Array.isArray(list) ? list : []).slice(0, MAX_ROWS).map(parseMineRow).filter((r): r is SubRow => r !== null);
}

function refusalField(payload: unknown, field: 'code' | 'detail'): string {
    const body = bag(payload);
    const nested = bag(body.detail)[field];
    const flat = body[field];
    return typeof nested === 'string' ? nested : typeof flat === 'string' ? flat : '';
}

export function asRefusal(error: unknown): Error & { detail?: { code: string; detail?: string }; status?: number } {
    if (error instanceof ApiError) {
        const wrapped: Error & { detail?: { code: string; detail?: string }; status?: number } = new Error(error.message);
        wrapped.status = error.status;
        const code = error.code || refusalField(error.payload, 'code');
        if (code) wrapped.detail = { code, detail: refusalField(error.payload, 'detail') };
        return wrapped;
    }
    return error instanceof Error ? error : new Error(String(error));
}

export async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    try {
        return await authFetch<T>(path, init);
    } catch (error) {
        throw asRefusal(error);
    }
}

export function jsonPost(body: unknown): RequestInit {
    return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export async function fetchMine(force = false): Promise<SubRow[]> {
    return parseMine(await call<unknown>(`/catalog/submissions/mine${force ? '?refresh=true' : ''}`));
}

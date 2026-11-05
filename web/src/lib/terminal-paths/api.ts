import { authFetch } from '../../opscenter/api/auth.svelte';

export interface ResolvedPath {
    text: string;
    path: string | null;
    kind: 'file' | 'dir' | null;
    line: number | null;
}

export const ANSWER_TTL_MS = 30_000;

export const CACHE_MAX = 500;

const cache = new Map<string, { at: number; answer: ResolvedPath }>();

function keyOf(sessionId: string, text: string): string {
    return `${sessionId}\u0000${text}`;
}

export function cachedAnswer(sessionId: string, text: string, now: number = Date.now()): ResolvedPath | null {
    const hit = cache.get(keyOf(sessionId, text));
    return hit && now - hit.at < ANSWER_TTL_MS ? hit.answer : null;
}

export async function resolvePaths(sessionId: string, texts: string[]): Promise<Map<string, ResolvedPath>> {
    const now = Date.now();
    const out = new Map<string, ResolvedPath>();
    const ask: string[] = [];
    for (const text of new Set(texts)) {
        const hit = cachedAnswer(sessionId, text, now);
        if (hit) out.set(text, hit);
        else ask.push(text);
    }
    if (ask.length === 0) return out;
    const answer = await authFetch<{ paths: ResolvedPath[] }>(`/sessions/${encodeURIComponent(sessionId)}/paths/resolve`, {
        method: 'POST', body: JSON.stringify({ texts: ask }),
    });
    for (const row of answer.paths) {
        out.set(row.text, row);
        cache.delete(keyOf(sessionId, row.text));
        cache.set(keyOf(sessionId, row.text), { at: now, answer: row });
    }
    while (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value as string);
    return out;
}

export async function openOutside(sessionId: string, text: string, app: 'finder' | 'browser'): Promise<void> {
    await authFetch(`/sessions/${encodeURIComponent(sessionId)}/paths/open`, {
        method: 'POST', body: JSON.stringify({ text, app }),
    });
}

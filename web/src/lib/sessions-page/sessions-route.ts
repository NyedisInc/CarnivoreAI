
export interface SessionsRoute {
    readonly session: string | null;
}

export const SESSIONS_TOP: SessionsRoute = { session: null };

export function sessionsHash(route: SessionsRoute): string {
    return route.session ? `#sessions/${encodeURIComponent(route.session)}` : '#sessions';
}

function segmentsAfter(hash: string | null | undefined, word: string): string[] | null {
    if (typeof hash !== 'string') return null;
    const parts = hash.trim().replace(/^#/, '').split('/').filter((p) => p !== '');
    if (parts[0] !== word) return null;
    try {
        return parts.slice(1).map(decodeURIComponent);
    } catch {
        return [];
    }
}

function legacyPlace(rest: readonly string[]): { project: string | null; session: string | null } {
    const tail = rest[0] === 'c' && rest[1] !== undefined ? rest.slice(2) : rest[0] === 'c' ? [] : rest;
    return { project: tail[0] ?? null, session: tail[0] ? (tail[1] ?? null) : null };
}

export function sessionsRouteOfHash(hash: string | null | undefined): SessionsRoute | null {
    const own = segmentsAfter(hash, 'sessions');
    if (own) return own[0] === undefined ? SESSIONS_TOP : { session: own[0] };
    const old = segmentsAfter(hash, 'projects');
    return old ? { session: legacyPlace(old).session } : null;
}

export function projectOfHash(hash: string | null | undefined): string | null {
    const old = segmentsAfter(hash, 'projects');
    return old ? legacyPlace(old).project : null;
}

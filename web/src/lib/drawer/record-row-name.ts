
interface ListedRow {
    name?: unknown;
    session_uuid?: unknown;
    asleep?: unknown;
    closed?: unknown;
    archived?: unknown;
}

export interface RowClaims {
    liveNames: Map<string, string | null>;
    liveUuids: Set<string>;
    taken: Set<string>;
}

export function claimsOf(rows: readonly ListedRow[]): RowClaims {
    const claims: RowClaims = { liveNames: new Map(), liveUuids: new Set(), taken: new Set() };
    for (const r of Array.isArray(rows) ? rows : []) {
        if (!r || typeof r.name !== 'string') continue;
        claims.taken.add(r.name);
        if (r.asleep === true || r.closed === true || r.archived === true) continue;
        const uuid = typeof r.session_uuid === 'string' && r.session_uuid ? r.session_uuid : null;
        claims.liveNames.set(r.name, uuid);
        if (uuid) claims.liveUuids.add(uuid);
    }
    return claims;
}

export function liveRowIs(claims: RowClaims, uuid: string, name: string | null | undefined): boolean {
    if (claims.liveUuids.has(uuid)) return true;
    return !!name && claims.liveNames.has(name) && claims.liveNames.get(name) === null;
}

export function rowNameFor(claims: RowClaims, prefix: string, uuid: string, tmuxName: string | null | undefined): string {
    const name = tmuxName && !claims.taken.has(tmuxName) ? tmuxName : `${prefix}${uuid}`;
    claims.taken.add(name);
    return name;
}

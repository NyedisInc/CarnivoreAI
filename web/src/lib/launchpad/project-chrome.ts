/* could not be read */
import type { ProjectAuthority, ProjectRow } from '../sessions/types';

export type ArchivedNotice =
    | { kind: 'silent' }
    | { kind: 'count'; count: number }
    | { kind: 'unknown' };

export function archivedNotice(
    archivedFetchOk: boolean | null,
    projects: ProjectRow[],
): ArchivedNotice {
    if (archivedFetchOk === null || archivedFetchOk === undefined) {
        return { kind: 'silent' };
    }
    if (archivedFetchOk === false) return { kind: 'unknown' };
    const count = (projects || []).filter((p) => p && p.archived_at).length;
    return { kind: 'count', count };
}

/* could not did not answer */
export type AuthorityBanner =
    | { kind: 'none' }
    | { kind: 'degraded'; mode: string; writable: boolean; message: string }
    | { kind: 'unknown' };

export function authorityBanner(
    authority: ProjectAuthority | null | undefined,
): AuthorityBanner {
    if (authority === null || authority === undefined) return { kind: 'unknown' };
    if (!authority.degraded) return { kind: 'none' };
    const mode = authority.mode || '';
    return {
        kind: 'degraded',
        mode,
        writable: !!authority.writable,
        message: authority.message || mode,
    };
}

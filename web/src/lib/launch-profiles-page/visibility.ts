import type { ProfileRow } from './api';

export interface VisibilityOptions {
    showHidden?: boolean;
    keep?: readonly (string | null | undefined)[];
}

export function visibleProfiles<T extends Pick<ProfileRow, 'id' | 'installed'>>(rows: readonly T[], opts: VisibilityOptions = {}): T[] {
    if (opts.showHidden) return [...rows];
    const keep = new Set((opts.keep ?? []).filter((id): id is string => !!id));
    return rows.filter((r) => r.installed !== false || keep.has(r.id));
}

export function hiddenCount(rows: readonly Pick<ProfileRow, 'installed'>[]): number {
    return rows.filter((r) => r.installed === false).length;
}

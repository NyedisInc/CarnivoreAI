import { hostWindow } from './env';

interface Globals {
    TerminalController?: { _currentSession?: unknown };
    ListingPush?: { rows?(name: string): unknown[] | null };
}

function projectOf(row: unknown): number | null {
    const id = (row as { project_id?: unknown } | null)?.project_id;
    return typeof id === 'number' && Number.isInteger(id) && id > 0 ? id : null;
}

function sessionIdOf(row: unknown): string | null {
    const r = row as { id?: unknown; session?: { id?: unknown } } | null;
    const id = r?.session?.id ?? r?.id;
    return typeof id === 'string' ? id : null;
}

export function currentProjectId(win: unknown = hostWindow()): number | null {
    const g = (win ?? {}) as Globals;
    const current = g.TerminalController?._currentSession ?? null;
    if (!current) return null;
    const direct = projectOf(current);
    if (direct !== null) return direct;
    const id = sessionIdOf(current);
    if (!id) return null;
    let rows: unknown[] | null | undefined = null;
    try {
        rows = g.ListingPush?.rows?.('list');
    } catch (err) {
        console.warn('currentProjectId: could not read the pushed listing', err);
        return null;
    }
    const row = (rows ?? []).find((r) => sessionIdOf(r) === id);
    return projectOf(row ?? null);
}

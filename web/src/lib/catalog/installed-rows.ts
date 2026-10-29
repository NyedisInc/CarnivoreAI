import type { InstalledItem } from './types';

export interface ScopeChip {
    key: string;
    scope: 'global' | 'project';
    path: string | null;
    folder: string | null;
    installId: string | null;
    update: boolean;
}

export function groupInstalled(rows: readonly InstalledItem[]): Record<string, InstalledItem[]> {
    const out: Record<string, InstalledItem[]> = {};
    for (const row of rows) {
        const key = row && row.item_id;
        if (!key) continue;
        (out[key] ??= []).push(row);
    }
    return out;
}

export function sameCopy(a: InstalledItem, b: InstalledItem): boolean {
    if (a.install_id && b.install_id) return a.install_id === b.install_id;
    return (a.scope ?? 'global') === (b.scope ?? 'global') && (a.project_path ?? null) === (b.project_path ?? null);
}

function folderOf(path: string | null | undefined): string | null {
    if (!path) return null;
    return path.split('/').filter(Boolean).pop() ?? path;
}

export function scopeChips(rows: readonly InstalledItem[] | undefined): ScopeChip[] {
    const chips = (rows ?? []).map((row): ScopeChip => {
        const project = row.scope === 'project';
        return {
            key: project ? (row.project_path ?? row.install_id ?? 'project') : 'global',
            scope: project ? 'project' : 'global',
            path: project ? (row.project_path ?? null) : null,
            folder: project ? folderOf(row.project_path) : null,
            installId: row.install_id ?? null,
            update: row.update_available === true,
        };
    });
    return chips.sort((a, b) =>
        a.scope === b.scope ? (a.folder ?? '').localeCompare(b.folder ?? '') : a.scope === 'global' ? -1 : 1,
    );
}

export function anyUpdate(rows: readonly InstalledItem[] | undefined): boolean {
    return (rows ?? []).some((row) => row.update_available === true);
}

export function harnessesOf(row: InstalledItem): string[] {
    const seen: string[] = [];
    for (const target of row.targets ?? []) {
        const name = target && target.harness;
        if (typeof name === 'string' && name && !seen.includes(name)) seen.push(name);
    }
    return seen;
}

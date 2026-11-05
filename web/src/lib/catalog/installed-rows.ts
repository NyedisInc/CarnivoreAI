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

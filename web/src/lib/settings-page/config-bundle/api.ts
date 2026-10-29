import { ApiError, authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type ImportMode = 'merge' | 'replace';

export interface ChangeLine {
    readonly path: string;
    readonly kind: 'added' | 'changed' | 'removed';
    readonly before: string | null;
    readonly after: string | null;
}

export interface ImportAnswer {
    readonly status: 'preview' | 'applied' | 'unchanged';
    readonly dry_run: boolean;
    readonly mode: ImportMode;
    readonly changes: readonly ChangeLine[];
    readonly counts: { readonly added: number; readonly changed: number; readonly removed: number };
    readonly truncated: boolean;
    readonly stripped: readonly string[];
    readonly ignored: readonly string[];
    readonly backup: string | null;
    readonly source: { readonly source_host: string; readonly from_other_host: boolean; readonly app_version: string };
}

export class BundleFileError extends Error {}

export function fetchBundle(fetcher: Fetcher = authFetch): Promise<Record<string, unknown>> {
    return fetcher<Record<string, unknown>>('/config/export');
}

export function sendImport(
    bundle: Record<string, unknown>,
    mode: ImportMode,
    dryRun: boolean,
    fetcher: Fetcher = authFetch,
): Promise<ImportAnswer> {
    return fetcher<ImportAnswer>('/config/import', {
        method: 'POST',
        body: JSON.stringify({ bundle, mode, dry_run: dryRun }),
    });
}

export function parseBundleText(text: string): Record<string, unknown> {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw new BundleFileError('not json');
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new BundleFileError('not an object');
    return parsed as Record<string, unknown>;
}

export function bundleFilename(bundle: Record<string, unknown>): string {
    const stamp = typeof bundle.exported_at === 'string' ? bundle.exported_at.slice(0, 10).replaceAll('-', '') : '';
    return `carnivore-config-${stamp || 'export'}.json`;
}

export function errorText(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = (error.payload as { detail?: unknown } | null)?.detail;
        if (Array.isArray(detail)) return detail.map(String).join('; ');
        return error.message;
    }
    return error instanceof Error ? error.message : String(error);
}

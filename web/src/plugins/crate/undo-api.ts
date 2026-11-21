import { ApiError, authFetch, downloadBlob, type Translate } from '../sdk';
import { num, obj, objects, ROUTE, str, type Fetcher } from './crate-api';
import type { RemoveTarget } from './folder-crates-api';
import type { Finding } from './import-api';

export interface RestoredImport {
    readonly importId: string;
    readonly state: string;
    readonly projectName: string | null;
    readonly finishedAt: string | null;
    readonly undoneAt: string | null;
    readonly sessions: number;
    readonly files: number | null;
}

export interface UndoPreview {
    readonly ok: boolean;
    readonly blockers: readonly Finding[];
    readonly rowsToRemove: number;
    readonly rowsToPutBack: number;
    readonly kept: readonly { readonly what: string; readonly why: string }[];
    readonly files: number;
    readonly folders: number;
}

export interface UndoOutcome {
    readonly rowsDeleted: number;
    readonly rowsRestored: number;
    readonly filesRemoved: number;
    readonly foldersRemoved: number;
    readonly kept: readonly { readonly what: string; readonly why: string }[];
    readonly errors: readonly string[];
}

export function parseRestored(raw: unknown): RestoredImport | null {
    const o = obj(raw);
    const importId = o ? str(o.import_id) : null;
    if (!o || !importId) return null;
    const files = obj(o.files);
    return {
        importId, state: str(o.state) ?? 'done', projectName: str(obj(o.project)?.name), finishedAt: str(o.finished_at), undoneAt: str(o.undone_at),
        sessions: objects(o.sessions).length, files: num(files?.written),
    };
}

export async function fetchRestored(fetcher: Fetcher = authFetch): Promise<RestoredImport[]> {
    const answer = obj(await fetcher<unknown>(`${ROUTE}/imports`));
    return objects(answer?.imports).flatMap((r) => {
        const row = parseRestored(r);
        return row ? [row] : [];
    });
}

function keptOf(raw: unknown): { what: string; why: string }[] {
    return objects(raw).flatMap((k) => (str(k.what) ? [{ what: str(k.what)!, why: str(k.why) ?? '' }] : []));
}

export async function fetchUndoPreview(importId: string, fetcher: Fetcher = authFetch): Promise<UndoPreview> {
    const a = obj(await fetcher<unknown>(`${ROUTE}/imports/${encodeURIComponent(importId)}/undo`));
    return {
        ok: a?.ok === true, rowsToRemove: num(a?.rows_to_remove) ?? 0, rowsToPutBack: num(a?.rows_to_put_back) ?? 0, files: num(a?.files) ?? 0, folders: num(a?.folders) ?? 0,
        blockers: objects(a?.blockers).flatMap((b) => (str(b.code) ? [{ code: str(b.code)!, detail: str(b.detail) ?? '' }] : [])),
        kept: keptOf(a?.kept),
    };
}

export async function undoImport(importId: string, fetcher: Fetcher = authFetch): Promise<UndoOutcome> {
    const a = obj(await fetcher<unknown>(`${ROUTE}/imports/${encodeURIComponent(importId)}/undo`, { method: 'POST' }));
    const undo = obj(a?.undo);
    const rows = obj(undo?.rows);
    return {
        rowsDeleted: num(rows?.deleted) ?? 0, rowsRestored: num(rows?.restored) ?? 0, filesRemoved: num(undo?.files_removed) ?? 0, foldersRemoved: num(undo?.folders_removed) ?? 0, kept: keptOf(undo?.kept),
        errors: [...(Array.isArray(undo?.errors) ? undo.errors : []), ...(Array.isArray(undo?.file_errors) ? undo.file_errors : [])].map(String),
    };
}

export function undoBlockers(error: unknown): Finding[] {
    const detail = error instanceof ApiError ? obj(obj(error.payload)?.detail) : null;
    return detail && detail.code === 'undo_blocked'
        ? objects(detail.detail).flatMap((b) => (str(b.code) ? [{ code: str(b.code)!, detail: str(b.detail) ?? '' }] : []))
        : [];
}

export function undoBlockerSentence(finding: Finding, t: Translate): string {
    const key = `cplug.crate.undo.blocked.${finding.code}`;
    const said = t(key);
    return said !== key ? said : finding.detail || finding.code;
}

export function keptWhy(why: string, t: Translate): string {
    const key = `cplug.crate.undo.why.${why.replace(/[^a-z]+/gi, '_').toLowerCase()}`;
    const said = t(key);
    return said !== key ? said : why;
}

function downloadPath(target: RemoveTarget, part: 'crate' | 'sha256'): string {
    const base = 'bundleId' in target
        ? `${ROUTE}/bundles/${encodeURIComponent(target.bundleId)}/download`
        : `${ROUTE}/folders/${target.folder}/crates/${encodeURIComponent(target.name)}/download`;
    return part === 'sha256' ? `${base}?part=sha256` : base;
}

export async function downloadCrate(target: RemoveTarget, fallbackName: string, part: 'crate' | 'sha256' = 'crate', fetcher: Fetcher = authFetch): Promise<string> {
    const blob = await fetcher<Blob>(downloadPath(target, part));
    return downloadBlob(blob instanceof File && blob.name ? blob.name : fallbackName, blob);
}

import { t } from '../i18n/index.svelte';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { failureReason } from '../errors/failure-reason';
import { downloadBlob } from '../manager-frame/download';
import { readOpenFile, type OpenFileInfo } from './api.svelte';
import { bufferOf, isDirty } from './buffers.svelte';
import { downloadRoute, isDownloading, setDownloading } from './download-row.svelte';
import { appConfirm, saveFile, type ConfirmFn, type SaveOutcome } from './save-flow';

export { downloadRoute, downloadableRow } from './download-row.svelte';

const OBJECT_URL_LIFETIME_MS = 60_000;

export type DownloadOutcome =
    | { kind: 'started' }
    | { kind: 'cancelled' }
    | { kind: 'busy' }
    /* save and download */
    | { kind: 'not_saved'; outcome: SaveOutcome }
    | { kind: 'failed'; detail: string };

export interface DownloadDeps {
    confirm: ConfirmFn;
    save: (file: Pick<OpenFileInfo, 'id' | 'path'>) => Promise<SaveOutcome>;
    sensitive: (file: OpenFileInfo) => Promise<boolean>;
    fetchBytes: (route: string) => Promise<Blob>;
    saveAs: (bytes: Blob, fallbackName: string) => void;
}

function saveFetched(bytes: Blob, fallbackName: string): void {
    const name = bytes instanceof File && bytes.name ? bytes.name : fallbackName;
    downloadBlob(name, bytes, document, OBJECT_URL_LIFETIME_MS);
}

function liveSave(file: Pick<OpenFileInfo, 'id' | 'path'>): Promise<SaveOutcome> {
    return saveFile(file.id, file.path);
}

async function liveSensitive(file: OpenFileInfo): Promise<boolean> {
    const buffer = bufferOf(file.id);
    if (buffer) return buffer.isSensitive;
    try {
        return (await readOpenFile(file.id)).is_sensitive === true;
    } catch (err) {
        console.warn('open files: could not tell whether the file is sensitive', { id: file.id, error: err });
        return false;
    }
}

export const liveDownloadDeps: DownloadDeps = {
    confirm: appConfirm(),
    save: liveSave,
    sensitive: liveSensitive,
    fetchBytes: (route) => authFetch<Blob>(route),
    saveAs: saveFetched,
};

async function fetchAndSave(file: OpenFileInfo, deps: DownloadDeps): Promise<DownloadOutcome> {
    try {
        deps.saveAs(await deps.fetchBytes(downloadRoute(file.id)), file.title);
        return { kind: 'started' };
    } catch (err) {
        console.warn('open files: download failed', { id: file.id, error: err });
        return { kind: 'failed', detail: failureReason(err) };
    }
}

async function flow(file: OpenFileInfo, dirty: boolean, deps: DownloadDeps): Promise<DownloadOutcome> {
    if (dirty) {
        const ok = await deps.confirm(t('files.download.dirty.title'), t('files.download.dirty.message', { name: file.title }),
            t('files.download.dirty.detail'), t('files.download.dirty.save'), t('files.editor.cancel'));
        if (!ok) return { kind: 'cancelled' };
        const outcome = await deps.save(file);
        return outcome.kind === 'saved' ? fetchAndSave(file, deps) : { kind: 'not_saved', outcome };
    }
    if (await deps.sensitive(file)) {
        const ok = await deps.confirm(t('files.download.sensitive.title'), t('files.download.sensitive.message', { path: file.path }),
            t('files.download.sensitive.detail'), t('files.download.sensitive.confirm'), t('files.editor.cancel'));
        if (!ok) return { kind: 'cancelled' };
    }
    return fetchAndSave(file, deps);
}

export async function requestDownload(file: OpenFileInfo, dirty: boolean = isDirty(file.id), deps: DownloadDeps = liveDownloadDeps): Promise<DownloadOutcome> {
    if (isDownloading(file.id)) return { kind: 'busy' };
    setDownloading(file.id, true);
    try {
        return await flow(file, dirty, deps);
    } finally {
        setDownloading(file.id, false);
    }
}

export function outcomeText(outcome: DownloadOutcome): string | null {
    if (outcome.kind === 'failed') return t('files.download.failed', { detail: outcome.detail });
    if (outcome.kind !== 'not_saved') return null;
    const save = outcome.outcome;
    if (save.kind === 'stale') return t(save.gone ? 'files.editor.stale.deleted' : 'files.editor.stale');
    if (save.kind === 'invalid_json') return t('files.editor.invalid_json', { detail: save.detail });
    if (save.kind === 'failed') return t('files.editor.save_failed', { detail: save.detail });
    return null;
}

export interface DownloadOptions {
    dirty?: boolean;
    save?: DownloadDeps['save'];
}

export async function downloadWithMessage(file: OpenFileInfo, options: DownloadOptions = {}): Promise<string | null> {
    const deps = options.save ? { ...liveDownloadDeps, save: options.save } : liveDownloadDeps;
    return outcomeText(await requestDownload(file, options.dirty ?? isDirty(file.id), deps));
}

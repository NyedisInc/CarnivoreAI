import { t } from '../i18n/index.svelte';
import {
    FILE_CHANGED_ON_DISK,
    readOpenFile,
    refusalCode,
    staleSha256,
    saveOpenFile,
    type OpenFileContent,
    type SaveOpenFileBody,
    type SaveOpenFileResult,
} from './api.svelte';
import { bufferOf, markSaved } from './buffers.svelte';

export type SaveOutcome =
    | { kind: 'saved'; backedUp: boolean }
    | { kind: 'invalid_json'; detail: string }
    | { kind: 'cancelled' }
    | { kind: 'stale'; gone: boolean }
    | { kind: 'failed'; detail: string };

export type ConfirmFn = (title: string, message: string, detail: string, confirmLabel: string, cancelLabel: string) => Promise<boolean>;

export interface SaveDeps {
    confirm: ConfirmFn;
    save: (id: string, body: SaveOpenFileBody) => Promise<SaveOpenFileResult>;
    read: (id: string) => Promise<OpenFileContent>;
}

export function appConfirm(): ConfirmFn {
    return async (title, message, detail, confirmLabel, cancelLabel) => {
        const app = (globalThis as { App?: { showConfirmModal?: (...a: unknown[]) => Promise<boolean> } }).App;
        if (typeof app?.showConfirmModal !== 'function') {
            console.error('open files: the confirm modal is not on the page; the save was not sent');
            return false;
        }
        return app.showConfirmModal(title, message, detail, confirmLabel, cancelLabel);
    };
}

export const liveSaveDeps: SaveDeps = { confirm: appConfirm(), save: saveOpenFile, read: readOpenFile };

export async function saveFile(id: string, path: string, overwrite = false, deps: SaveDeps = liveSaveDeps): Promise<SaveOutcome> {
    const buffer = bufferOf(id);
    if (!buffer || buffer.readOnly) return { kind: 'cancelled' };
    const content = buffer.current;
    if (path.toLowerCase().endsWith('.json')) {
        try {
            JSON.parse(content);
        } catch (err) {
            return { kind: 'invalid_json', detail: err instanceof Error ? err.message : String(err) };
        }
    }
    const body: SaveOpenFileBody = overwrite ? { content, overwrite: true } : { content, expected_sha256: buffer.sha256 };
    if (buffer.isExecutable) {
        const ok = await deps.confirm(t('files.editor.confirm.executable.title'), t('files.editor.confirm.executable.message', { path }),
            t('files.editor.confirm.backup'), t('files.editor.save'), t('files.editor.cancel'));
        if (!ok) return { kind: 'cancelled' };
        body.acknowledge_executable = true;
    }
    if (buffer.isSensitive) {
        const ok = await deps.confirm(t('files.editor.confirm.sensitive.title'), t('files.editor.confirm.sensitive.message', { path }),
            t('files.editor.confirm.backup'), t('files.editor.save'), t('files.editor.cancel'));
        if (!ok) return { kind: 'cancelled' };
        body.acknowledge_sensitive = true;
    }
    try {
        const result = await deps.save(id, body);
        markSaved(id, content, result.sha256 ?? (await revisionAfterSave(id, content, deps)));
        return { kind: 'saved', backedUp: !!result.backed_up };
    } catch (err) {
        if (refusalCode(err) === FILE_CHANGED_ON_DISK) return { kind: 'stale', gone: staleSha256(err) === null };
        console.warn('open files: save refused', { id, error: err });
        return { kind: 'failed', detail: err instanceof Error ? err.message : String(err) };
    }
}

async function revisionAfterSave(id: string, saved: string, deps: SaveDeps): Promise<string> {
    try {
        const read = await deps.read(id);
        if (read.viewable && read.content === saved && read.sha256) return read.sha256;
    } catch (err) {
        console.warn('open files: re-read after a save failed', { id, error: err });
    }
    return '';
}

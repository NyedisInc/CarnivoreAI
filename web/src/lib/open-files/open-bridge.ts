import { t } from '../i18n/index.svelte';
import { dismissBrowserScreen, openBrowser } from '../browser/screen-host';
import { BROWSER_ID } from '../browser/browser-id';
import { panelInstance } from '../mount';
import { deleteOpenFile, fileById, postOpenFile, postOpenFilePath } from './api.svelte';
import { dropBuffer, isDirty } from './buffers.svelte';
import { rememberSessionId, sessionUuidFor, type SessionRef } from './session-ref';
import { appConfirm, type ConfirmFn } from './save-flow';

export interface OpenFromDrawer extends SessionRef {
    root: 'user' | 'workdir';
    path: string;
    kind?: 'file' | 'diff';
}

export type OpenResult = 'opened' | 'unavailable' | 'refused';

export async function openFromDrawer(request: OpenFromDrawer): Promise<OpenResult> {
    let uuid: string | null;
    try {
        uuid = await sessionUuidFor(request);
    } catch (err) {
        console.warn('open files: the session records could not be read', err);
        return 'unavailable';
    }
    if (!uuid) return 'unavailable';
    rememberSessionId(uuid, request.sessionId);
    try {
        const row = await postOpenFile({ root: request.root, path: request.path, session_uuid: uuid, kind: request.kind ?? 'file' });
        return openBrowser(row.id) ? 'opened' : 'refused';
    } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        console.warn('open files: the open was refused', { root: request.root, kind: request.kind, error: detail });
        globalThis.alert?.(t('files.editor.open_failed', { detail }));
        return 'refused';
    }
}

export async function openFromPath(path: string): Promise<void> {
    const row = await postOpenFilePath(path);
    if (!openBrowser(row.id)) throw new Error(t('opscenter.cell.files.open.refused'));
}

interface ShowingHandle {
    showing?: () => string | null;
}

export async function closeFileRow(id: string, confirm: ConfirmFn = appConfirm()): Promise<boolean> {
    if (!BROWSER_ID.test(id)) return false;
    if (isDirty(id)) {
        const name = fileById(id)?.title ?? '';
        const ok = await confirm(t('files.editor.discard.title'), t('files.editor.discard.message', { name }),
            t('files.editor.discard.detail'), t('files.editor.discard.confirm'), t('files.editor.cancel'));
        if (!ok) return false;
    }
    dropBuffer(id);
    await deleteOpenFile(id);
    const screen = panelInstance('browser-screen') as ShowingHandle | null;
    if (screen?.showing?.() === id) dismissBrowserScreen();
    return true;
}

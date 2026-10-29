import { t } from '../i18n/index.svelte';
import { openFiles, postOpenFile, postOpenFilePath, type OpenFileInfo, type OpenFileRequest } from './api.svelte';
import { bufferIds, dropBuffer, isDirty, moveBuffer } from './buffers.svelte';
import { appConfirm, type ConfirmFn } from './save-flow';

export interface OrphanDeps {
    confirm: ConfirmFn;
    reopen: (request: OpenFileRequest) => Promise<OpenFileInfo>;
    alert: (text: string) => void;
}

export const liveOrphanDeps: OrphanDeps = {
    confirm: appConfirm(),
    reopen: postOpenFile,
    alert: (text) => globalThis.alert?.(text),
};

const lastSeen = new Map<string, OpenFileInfo>();
const asking = new Set<string>();

export async function reconcileBuffers(list: readonly OpenFileInfo[], deps: OrphanDeps = liveOrphanDeps): Promise<void> {
    const present = new Set(list.map((f) => f.id));
    for (const row of list) lastSeen.set(row.id, row);
    const questions: Promise<void>[] = [];
    for (const id of bufferIds()) {
        if (present.has(id) || asking.has(id)) continue;
        if (!isDirty(id)) {
            dropBuffer(id);
            lastSeen.delete(id);
            continue;
        }
        asking.add(id);
        questions.push(askAbout(id, deps).finally(() => asking.delete(id)));
    }
    for (const id of [...lastSeen.keys()]) {
        if (!present.has(id) && !asking.has(id) && !bufferIds().includes(id)) lastSeen.delete(id);
    }
    await Promise.all(questions);
}

async function askAbout(id: string, deps: OrphanDeps): Promise<void> {
    const row = lastSeen.get(id);
    const name = row?.title ?? id;
    const discard = await deps.confirm(t('files.editor.orphan.title'), t('files.editor.orphan.message', { name }),
        t('files.editor.orphan.detail'), t('files.editor.discard.confirm'), t('files.editor.orphan.keep'));
    if (discard) {
        dropBuffer(id);
        lastSeen.delete(id);
        return;
    }
    if (!row) {
        console.warn('open files: a departed row with edits cannot be reopened; its row was never seen', { id });
        return;
    }
    try {
        const reopened = row.root === 'absolute' ? await postOpenFilePath(row.path) :
            await deps.reopen({ root: row.root, path: row.path, session_uuid: row.session_uuid, kind: row.kind });
        if (moveBuffer(id, reopened.id)) {
            lastSeen.delete(id);
            lastSeen.set(reopened.id, reopened);
        }
    } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        console.warn('open files: reopening a row with edits failed', { id, error: detail });
        deps.alert(t('files.editor.orphan.reopen_failed', { name, detail }));
    }
}

export function watchOrphans(): () => void {
    return $effect.root(() => {
        $effect(() => {
            const list = openFiles.status === 'ok' ? openFiles.data : null;
            if (list) void reconcileBuffers(list);
        });
    });
}

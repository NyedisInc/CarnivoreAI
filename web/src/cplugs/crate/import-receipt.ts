import { authFetch } from '../sdk';
import { obj, objects, str, type Fetcher } from './crate-api';
import type { Finding } from './import-api';

export interface RestoredSession {
    readonly sessionUuid: string;
    readonly conversationId: string | null;
    readonly title: string | null;
}

export interface ImportReceiptView {
    readonly importId: string;
    readonly state: string;
    readonly projectName: string | null;
    readonly projectRoot: string | null;
    readonly sessions: readonly RestoredSession[];
    readonly warnings: readonly Finding[];
    readonly notRestored: readonly { readonly what: string; readonly why: string }[];
    readonly keptBeside: readonly string[];
    readonly sideFolder: string | null;
    readonly patchKept: boolean;
}

export interface WakeAnswer {
    readonly status: string;
    readonly detail: string;
}

export function parseImportReceipt(raw: unknown): ImportReceiptView | null {
    const o = obj(raw);
    const importId = o ? str(o.import_id) : null;
    if (!o || !importId) return null;
    const titles = new Map(objects(o.conversations).flatMap((c) => (str(c.id) ? [[str(c.id)!, str(c.title)] as const] : [])));
    const project = obj(o.project);
    const boards = objects(obj(o.plugin_data)?.boards).filter((b) => str(b.state) === 'beside').flatMap((b) => (str(b.path) ? [str(b.path)!] : []));
    const files = obj(o.project_files);
    return {
        importId, state: str(o.state) ?? 'done', projectName: str(project?.name), projectRoot: str(project?.root),
        sessions: objects(o.sessions).flatMap((s) => {
            const sessionUuid = str(s.session_uuid);
            if (!sessionUuid) return [];
            const conversationId = str(s.conversation_id);
            return [{ sessionUuid, conversationId, title: conversationId ? titles.get(conversationId) ?? null : null }];
        }),
        warnings: objects(o.warnings).flatMap((w) => (str(w.code) ? [{ code: str(w.code)!, detail: str(w.detail) ?? '' }] : [])),
        notRestored: objects(o.not_restored).flatMap((n) => (str(n.what) ? [{ what: str(n.what)!, why: str(n.why) ?? '' }] : [])),
        keptBeside: boards,
        sideFolder: str(files?.path), patchKept: files?.patch === true,
    };
}

/* not asleep */
export async function wakeRestoredSession(sessionUuid: string, fetcher: Fetcher = authFetch): Promise<WakeAnswer> {
    const answer = obj(await fetcher<unknown>(`/sessions/${encodeURIComponent(sessionUuid)}/wake`, { method: 'POST' }));
    return { status: str(answer?.status) ?? 'started', detail: str(answer?.detail) ?? '' };
}

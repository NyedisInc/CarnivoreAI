
import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
import type { Translate } from '../sessions/types';
import type { CreateHost } from './create-host';
import type { FolderPickerSource, RemoteFolderAnswer, RemoteFolderListing } from './modal-types';

const UNREACHABLE = new Set(['not_paired', 'disconnected', 'timeout', 'unreachable', 'busy']);

/* older carnivore */
export function remoteBrowseNote(answer: RemoteFolderAnswer, computer: string, t: Translate): string | null {
    if (answer.status === 'ok') return null;
    if (answer.status === 'refused' && answer.code === 'not_found') return null;
    if (answer.status === 'refused') return t(PROJECT_CREATE_KEYS.remoteBrowseRefused, { computer });
    if (answer.reason === 'peer_too_old') return t(PROJECT_CREATE_KEYS.remoteBrowseOld, { computer });
    if (UNREACHABLE.has(answer.reason)) return t(PROJECT_CREATE_KEYS.remoteBrowseUnreachable, { computer });
    return t(PROJECT_CREATE_KEYS.remoteBrowseRefused, { computer });
}

const REFUSED_KEYS: Record<string, string> = {
    not_found: PROJECT_CREATE_KEYS.remotePickerNotFound,
    outside_allowed_roots: PROJECT_CREATE_KEYS.remotePickerOutside,
    unreadable: PROJECT_CREATE_KEYS.remotePickerUnreadable,
    invalid_path: PROJECT_CREATE_KEYS.remotePickerInvalid,
};

export function remoteFolderSource(host: Pick<CreateHost, 'remoteFolders'>, computer: { key: string; label: string }, t: Translate): FolderPickerSource {
    const params = { computer: computer.label };
    return {
        title: t(PROJECT_CREATE_KEYS.remotePickerTitle, params),
        truncatedText: t(PROJECT_CREATE_KEYS.remotePickerTruncated, params),
        async list(path: string | null): Promise<RemoteFolderListing> {
            const answer = await host.remoteFolders(computer.key, path);
            if (answer.status === 'ok') return answer;
            const code = answer.status === 'refused' ? answer.code : '';
            const key = REFUSED_KEYS[code] ?? PROJECT_CREATE_KEYS.remoteBrowseUnreachable;
            throw Object.assign(new Error(t(key, params)), { status: code === 'not_found' ? 404 : 0 });
        },
    };
}

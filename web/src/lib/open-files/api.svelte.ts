import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { repaintDrawer } from '../browser/drawer-repaint';

export const OPEN_FILES_TOPIC = 'open_files';

export const OPEN_FILES_POLL_MS = 5000;

export const FILE_CHANGED_ON_DISK = 'file_changed_on_disk';

export interface OpenFileInfo {
    id: string;
    kind: 'file' | 'diff';
    root: 'user' | 'workdir' | 'absolute';
    path: string;
    session_uuid: string;
    title: string;
    opened_at: number;
    seq: number;
}

export type CantShowReason = 'too_large' | 'not_text' | 'gone' | 'unavailable';

export interface OpenFileContent {
    id: string;
    viewable: boolean;
    reason?: CantShowReason;
    detail?: string;
    content?: string;
    sha256?: string;
    mtime_ns?: number;
    size?: number;
    is_executable?: boolean;
    is_sensitive?: boolean;
    read_only?: boolean;
}

export interface SaveOpenFileBody {
    content: string;
    expected_sha256?: string;
    overwrite?: boolean;
    acknowledge_executable?: boolean;
    acknowledge_sensitive?: boolean;
}

export interface SaveOpenFileResult {
    id: string;
    backed_up: boolean;
    is_executable: boolean;
    is_sensitive: boolean;
    sha256?: string | null;
    mtime_ns?: number | null;
}

export interface OpenFileRequest {
    root: 'user' | 'workdir';
    path: string;
    session_uuid: string;
    kind: 'file' | 'diff';
}

export const openFiles: Resource<OpenFileInfo[]> = resource<OpenFileInfo[]>(
    async () => (await authFetch<{ files: OpenFileInfo[] }>('/files/open')).files,
    {
        intervalMs: OPEN_FILES_POLL_MS, name: 'open_files', demo: () => [],
        topics: [OPEN_FILES_TOPIC], afterPush: () => repaintDrawer(),
    },
);

export function fileById(id: string): OpenFileInfo | null {
    return (openFiles.data ?? []).find((f) => f.id === id) ?? null;
}

export async function postOpenFile(request: OpenFileRequest): Promise<OpenFileInfo> {
    const answer = await authFetch<{ file: OpenFileInfo; reused: boolean }>('/files/open', {
        method: 'POST', body: JSON.stringify(request),
    });
    await openFiles.refresh(true);
    repaintDrawer();
    return answer.file;
}

export async function postOpenFilePath(path: string): Promise<OpenFileInfo> {
    const answer = await authFetch<{ file: OpenFileInfo; reused: boolean }>('/files/open/path', {
        method: 'POST', body: JSON.stringify({ path }),
    });
    await openFiles.refresh(true);
    repaintDrawer();
    return answer.file;
}

export async function deleteOpenFile(id: string): Promise<void> {
    await authFetch<void>(`/files/open/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await openFiles.refresh(true);
    repaintDrawer();
}

export function readOpenFile(id: string): Promise<OpenFileContent> {
    return authFetch<OpenFileContent>(`/files/open/${encodeURIComponent(id)}/content`);
}

export function saveOpenFile(id: string, body: SaveOpenFileBody): Promise<SaveOpenFileResult> {
    return authFetch<SaveOpenFileResult>(`/files/open/${encodeURIComponent(id)}/content`, {
        method: 'PUT', body: JSON.stringify(body),
    });
}

export function refusalCode(err: unknown): string | null {
    if (!(err instanceof ApiError)) return null;
    if (err.code) return err.code;
    const detail = (err.payload as { detail?: unknown } | null)?.detail;
    const code = detail && typeof detail === 'object' ? (detail as { code?: unknown }).code : null;
    return typeof code === 'string' ? code : null;
}

/* deleted on disk */
export function staleSha256(err: unknown): string | null | undefined {
    if (!(err instanceof ApiError)) return undefined;
    const detail = (err.payload as { detail?: unknown } | null)?.detail;
    if (!detail || typeof detail !== 'object' || !('sha256' in detail)) return undefined;
    const sha = (detail as { sha256?: unknown }).sha256;
    return typeof sha === 'string' ? sha : null;
}

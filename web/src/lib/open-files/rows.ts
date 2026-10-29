import type { OpenFileInfo } from './api.svelte';

export const FILE_ROW_PREFIX = 'browser:';

export interface FileDrawerRow {
    name: string;
    kind: 'browser';
    browser_id: string;
    file: true;
    file_kind: 'file' | 'diff';
    path: string;
    label: string;
    dirty: boolean;
    url: null;
    status: 'file' | 'dirty';
    created_at_epoch: number;
    last_work_at: null;
    project_id: null;
    project_name: null;
    working_dir: null;
    [field: string]: unknown;
}

export function fileDrawerRows(files: readonly OpenFileInfo[], dirty: (id: string) => boolean): FileDrawerRow[] {
    return files.map((f) => {
        const isDirty = f.kind === 'file' && dirty(f.id);
        return {
            name: FILE_ROW_PREFIX + f.id,
            kind: 'browser',
            browser_id: f.id,
            file: true,
            file_kind: f.kind,
            path: f.path,
            label: f.title,
            dirty: isDirty,
            url: null,
            status: isDirty ? 'dirty' : 'file',
            created_at_epoch: Number(f.opened_at) || 0,
            last_work_at: null,
            project_id: null,
            project_name: null,
            working_dir: null,
        };
    });
}

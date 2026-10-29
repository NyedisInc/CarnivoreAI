
export const FILE_DRAWER_EVENT = 'cloude:file-drawer';

export type FilesMode = 'drawer' | 'cell';

export interface FileDrawerDetail {
    open: boolean;
    mode?: FilesMode;
    directory?: string | null;
}

export const filesDrawer = $state<{
    open: boolean;
    mode: FilesMode;
    directory: string | null;
    slot: string | null;
}>({ open: false, mode: 'drawer', directory: null, slot: null });

let listening = false;

export function foldFileDrawer(detail: FileDrawerDetail | null | undefined): void {
    if (!detail) return;
    filesDrawer.open = !!detail.open;
    filesDrawer.mode = detail.mode === 'cell' ? 'cell' : 'drawer';
    filesDrawer.directory = detail.directory ?? null;
    if (!filesDrawer.open) filesDrawer.slot = null;
}

export function listenFileDrawer(): void {
    if (listening || typeof window === 'undefined' || typeof window.addEventListener !== 'function') return;
    listening = true;
    window.addEventListener(FILE_DRAWER_EVENT, (event) => {
        foldFileDrawer((event as CustomEvent<FileDrawerDetail>).detail);
    });
}

export function filesShowing(slot: string, directory: string | null): boolean {
    return filesDrawer.open && filesDrawer.mode === 'drawer'
        && filesDrawer.slot === slot && filesDrawer.directory === directory;
}

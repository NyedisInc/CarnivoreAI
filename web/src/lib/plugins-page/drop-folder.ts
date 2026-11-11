import { consentSheetOf, type SideloadSheet } from './sideload-switch';
import type { InstallConsent } from '../catalog/types';

export interface DropBridge {
    droppedPaths(files: FileList | File[]): string[];
}

export type DropProblem = 'not_folder' | 'no_path';

export function desktopBridge(win: Window = window): DropBridge | null {
    const bridge = (win as Window & { carnivoreDesktop?: Partial<DropBridge> }).carnivoreDesktop;
    return typeof bridge?.droppedPaths === 'function' ? (bridge as DropBridge) : null;
}

export function pathOfDrop(dt: DataTransfer, bridge: DropBridge | null): { path: string } | { problem: DropProblem } {
    const entry = dt.items?.[0]?.webkitGetAsEntry?.() ?? null;
    if (!entry?.isDirectory) return { problem: 'not_folder' };
    const first = dt.files?.[0];
    const path = bridge && first ? (bridge.droppedPaths([first])[0] ?? '') : '';
    return path ? { path } : { problem: 'no_path' };
}

export function folderOfPicked(picked: File, fullPath: string): string | null {
    const relative = picked.webkitRelativePath;
    const slash = relative.indexOf('/');
    if (slash < 0 || !fullPath) return null;
    const inside = relative.slice(slash);
    if (!fullPath.endsWith(inside) || fullPath.length <= inside.length) return null;
    const folder = fullPath.slice(0, fullPath.length - inside.length);
    return folder.endsWith(`/${relative.slice(0, slash)}`) ? folder : null;
}

export interface DropTarget {
    loadFolder(path: string, name?: string | null, consent?: InstallConsent): Promise<void>;
}

/* and the three */
export interface DropFlow {
    readonly sheet: SideloadSheet | null;
    readonly error: unknown;
    drop(path: string): Promise<void>;
    confirm(consent: InstallConsent): Promise<void>;
    cancel(): void;
}

export function createDropFlow(target: DropTarget): DropFlow {
    let path = '';
    const flow = {
        sheet: null as SideloadSheet | null,
        error: null as unknown,
        async drop(next: string): Promise<void> {
            path = next;
            flow.sheet = null;
            flow.error = null;
            try {
                await target.loadFolder(path, null);
            } catch (failure) {
                flow.sheet = consentSheetOf(failure);
                if (!flow.sheet) flow.error = failure;
            }
        },
        async confirm(consent: InstallConsent): Promise<void> {
            try {
                await target.loadFolder(path, null, consent);
                flow.sheet = null;
            } catch (failure) {
                flow.error = failure;
            }
        },
        cancel(): void {
            flow.sheet = null;
            flow.error = null;
        },
    };
    return flow;
}

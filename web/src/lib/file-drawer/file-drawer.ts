/* The file drawer's */
import { mountPanel } from '../mount';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import FileDrawerHeader from './FileDrawerHeader.svelte';
import FileDrawerGit from './FileDrawerGit.svelte';
import FileDrawerGitLine from './FileDrawerGitLine.svelte';
import type { DrawerPrefs, IgnoreStatus } from './drawer-prefs';
import { setDrawerGitTarget, type DrawerGitTarget, type FileDrawerTab } from './git-view.svelte';

export const HEADER_ID = 'config-editor-header';

export const GIT_ID = 'config-editor-git';
export const GIT_LINE_ID = 'config-editor-gitline';

export interface DrawerHeaderCallbacks {
    onQuery: (query: string) => void;
    onPrefs: (prefs: DrawerPrefs) => void;
    onRefresh: () => void;
    onCollapseAll: () => void;
    onNewFile: () => void;
    onClose: () => void;
    onComponent?: () => void;
    onSubmit?: () => void;
    onScopeUp?: () => void;
    onScopeClear?: () => void;
}

export interface DrawerHeaderHandle {
    prefs: () => DrawerPrefs;
    query: () => string;
    clearQuery: () => void;
    setIgnoreStatus: (status: IgnoreStatus) => void;
    escape: () => boolean;
    setComponentShown: (shown: boolean) => void;
    setScope: (label: string) => void;
}
export function mountFileDrawerHeader(callbacks: DrawerHeaderCallbacks): DrawerHeaderHandle | null {
    const handle = mountPanel(HEADER_ID, FileDrawerHeader, { ...callbacks });
    return handle as unknown as DrawerHeaderHandle | null;
}

export function showFilesCell(): boolean {
    terminalLayout.show('files');
    return true;
}

export interface DrawerGitCallbacks {
    tree: HTMLElement | null;
    onTab: (tab: FileDrawerTab) => void;
    onOpenDiff: (path: string, mountView: (body: HTMLElement) => () => void) => void;
    onOpenFile: (path: string, repoRoot: string, workdirPath: string | null) => void;
}

export interface DrawerGitHandle {
    setTarget: (target: DrawerGitTarget | null) => void;
}

export function mountFileDrawerGit(callbacks: DrawerGitCallbacks): DrawerGitHandle {
    mountPanel(GIT_ID, FileDrawerGit, { ...callbacks });
    mountPanel(GIT_LINE_ID, FileDrawerGitLine, {});
    return { setTarget: setDrawerGitTarget };
}

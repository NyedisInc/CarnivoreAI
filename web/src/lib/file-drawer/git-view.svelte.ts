
export type FileDrawerTab = 'files' | 'changed';

export interface DrawerGitTarget {
    sessionId: string;
    workdir: string;
    rowId?: number | null;
}

const TAB_KEY = 'carnivore.fileDrawerTab';

function readTab(): FileDrawerTab {
    try {
        return globalThis.localStorage?.getItem(TAB_KEY) === 'changed' ? 'changed' : 'files';
    } catch {
        return 'files';
    }
}

export const drawerGit = $state<{ sessionId: string; workdir: string; rowId: number | null; tab: FileDrawerTab }>({
    sessionId: '',
    workdir: '',
    rowId: null,
    tab: readTab(),
});

export function setDrawerGitTarget(target: DrawerGitTarget | null): void {
    const sessionId = target?.sessionId ?? '';
    const workdir = sessionId ? target?.workdir ?? '' : '';
    if (drawerGit.sessionId !== sessionId) drawerGit.sessionId = sessionId;
    if (drawerGit.workdir !== workdir) drawerGit.workdir = workdir;
    const rowId = sessionId && typeof target?.rowId === 'number' ? target.rowId : null;
    if (drawerGit.rowId !== rowId) drawerGit.rowId = rowId;
}

export function selectDrawerTab(tab: FileDrawerTab): void {
    drawerGit.tab = tab;
    try {
        globalThis.localStorage?.setItem(TAB_KEY, tab);
    } catch {
    }
}

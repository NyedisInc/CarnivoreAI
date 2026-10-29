
export type FileDrawerTab = 'files' | 'changed';

export interface DrawerGitTarget {
    sessionId: string;
    workdir: string;
}

const TAB_KEY = 'carnivore.fileDrawerTab';

function readTab(): FileDrawerTab {
    try {
        return globalThis.localStorage?.getItem(TAB_KEY) === 'changed' ? 'changed' : 'files';
    } catch {
        return 'files';
    }
}

export const drawerGit = $state<{ sessionId: string; workdir: string; tab: FileDrawerTab }>({
    sessionId: '',
    workdir: '',
    tab: readTab(),
});

export function setDrawerGitTarget(target: DrawerGitTarget | null): void {
    const sessionId = target?.sessionId ?? '';
    const workdir = sessionId ? target?.workdir ?? '' : '';
    if (drawerGit.sessionId !== sessionId) drawerGit.sessionId = sessionId;
    if (drawerGit.workdir !== workdir) drawerGit.workdir = workdir;
}

export function selectDrawerTab(tab: FileDrawerTab): void {
    drawerGit.tab = tab;
    try {
        globalThis.localStorage?.setItem(TAB_KEY, tab);
    } catch {
    }
}

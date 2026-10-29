import {
    loadSideload,
    removeSideload,
    resyncSideload,
    saveSideload,
    sideloadFolder,
    sideloadGit,
    type GitRequest,
    type SideloadItem,
    type SideloadStatus,
} from './sideload-switch';

export interface SideloadApi {
    load: () => Promise<SideloadStatus>;
    save: (enabled: boolean, hours?: number | null) => Promise<SideloadStatus>;
    folder: (path: string, name?: string | null) => Promise<unknown>;
    git: (request: GitRequest) => Promise<unknown>;
    resync: (item: SideloadItem) => Promise<unknown>;
    remove: (name: string) => Promise<unknown>;
}

export const LIVE_SIDELOAD_API: SideloadApi = {
    load: () => loadSideload(),
    save: (enabled, hours) => saveSideload(enabled, hours),
    folder: (path, name) => sideloadFolder(path, name),
    git: (request) => sideloadGit(request),
    resync: (item) => resyncSideload(item),
    remove: (name) => removeSideload(name),
};

export interface SideloadStore {
    readonly status: SideloadStatus | null;
    readonly failed: boolean;
    readonly busy: Readonly<Record<string, boolean>>;
    refresh(): Promise<void>;
    setSwitch(enabled: boolean, hours?: number | null): Promise<void>;
    loadFolder(path: string, name?: string | null): Promise<void>;
    loadGit(request: GitRequest): Promise<void>;
    resync(name: string): Promise<unknown>;
    remove(name: string): Promise<void>;
    item(name: string): SideloadItem | null;
}

export function createSideloadStore(api: SideloadApi = LIVE_SIDELOAD_API, onChanged: () => void = () => {}): SideloadStore {
    let status = $state<SideloadStatus | null>(null);
    let failed = $state(false);
    let busy = $state<Record<string, boolean>>({});

    async function refresh(): Promise<void> {
        try {
            status = await api.load();
            failed = false;
        } catch {
            failed = true;
        }
    }

    async function write(run: () => Promise<unknown>): Promise<unknown> {
        try {
            return await run();
        } finally {
            await refresh();
            onChanged();
        }
    }

    async function onName(name: string, run: () => Promise<unknown>): Promise<unknown> {
        busy = { ...busy, [name]: true };
        try {
            return await write(run);
        } finally {
            const { [name]: _done, ...rest } = busy;
            busy = rest;
        }
    }

    return {
        get status() { return status; },
        get failed() { return failed; },
        get busy() { return busy; },
        refresh,
        async setSwitch(enabled, hours) {
            status = await api.save(enabled, hours);
            failed = false;
            onChanged();
        },
        loadFolder: async (path, name) => { await write(() => api.folder(path, name)); },
        loadGit: async (request) => { await write(() => api.git(request)); },
        async resync(name) {
            const found = status?.items.find((i) => i.id === name);
            return found ? onName(name, () => api.resync(found)) : null;
        },
        remove: async (name) => { await onName(name, () => api.remove(name)); },
        item: (name) => status?.items.find((i) => i.id === name) ?? null,
    };
}

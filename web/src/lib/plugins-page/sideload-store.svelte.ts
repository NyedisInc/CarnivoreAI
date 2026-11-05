import {
    loadSideload,
    removeSideload,
    resyncSideload,
    saveSideload,
    sideloadFolder,
    sideloadGit,
    type GitRequest,
    kindOf,
    type SideloadItem,
    type SideloadKind,
    type SideloadStatus,
} from './sideload-switch';
import { isCplugIndexKind } from '../catalog/kind-display';
import type { InstallConsent } from '../catalog/types';

export interface SideloadApi {
    load: () => Promise<SideloadStatus>;
    save: (enabled: boolean, hours?: number | null) => Promise<SideloadStatus>;
    folder: (path: string, name?: string | null, consent?: InstallConsent) => Promise<unknown>;
    git: (request: GitRequest) => Promise<unknown>;
    resync: (item: SideloadItem, consent?: InstallConsent) => Promise<unknown>;
    remove: (name: string, kind?: SideloadKind) => Promise<unknown>;
}

export const LIVE_SIDELOAD_API: SideloadApi = {
    load: () => loadSideload(),
    save: (enabled, hours) => saveSideload(enabled, hours),
    folder: (path, name, consent) => sideloadFolder(path, name, undefined, consent),
    git: (request) => sideloadGit(request),
    resync: (item, consent) => resyncSideload(item, undefined, consent),
    remove: (name, kind) => removeSideload(name, kind),
};

export interface SideloadStore {
    readonly status: SideloadStatus | null;
    readonly failed: boolean;
    readonly busy: Readonly<Record<string, boolean>>;
    refresh(): Promise<void>;
    setSwitch(enabled: boolean, hours?: number | null): Promise<void>;
    loadFolder(path: string, name?: string | null, consent?: InstallConsent): Promise<void>;
    loadGit(request: GitRequest): Promise<void>;
    resync(name: string, kind?: SideloadKind, consent?: InstallConsent): Promise<unknown>;
    remove(name: string, kind?: SideloadKind): Promise<void>;
    item(name: string, kind?: SideloadKind): SideloadItem | null;
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

    function find(name: string, kind?: SideloadKind): SideloadItem | null {
        return status?.items.find((i) => i.id === name && (kind === undefined || kindOf(i) === kind)) ?? null;
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
        loadFolder: async (path, name, consent) => { await write(() => (consent ? api.folder(path, name, consent) : api.folder(path, name))); },
        loadGit: async (request) => { await write(() => api.git(request)); },
        async resync(name, kind, consent) {
            const found = find(name, kind);
            return found ? onName(name, () => (consent ? api.resync(found, consent) : api.resync(found))) : null;
        },
        remove: async (name, kind) => {
            const found = find(name, kind);
            const named = found && !isCplugIndexKind(kindOf(found)) ? kindOf(found) : undefined;
            await onName(name, () => (named ? api.remove(name, named) : api.remove(name)));
        },
        item: (name, kind) => find(name, kind),
    };
}

import { downloadJson } from './download';
import type {
    ManagerActionState,
    ManagerAdapter,
    ManagerItem,
    ManagerStatus,
    ManagerToggleState,
} from './types';

export interface ManagerController {
    readonly status: ManagerStatus;
    readonly items: readonly ManagerItem[];
    readonly toggles: Readonly<Record<string, ManagerToggleState>>;
    readonly canToggle: boolean;
    readonly actions: Readonly<Record<string, ManagerActionState>>;
    readonly canExport: boolean;
    readonly canRemove: boolean;
    readonly removed: string | null;
    load(): Promise<void>;
    toggle(id: string, enabled: boolean): Promise<void>;
    guard(id: string, work: () => Promise<void>): Promise<void>;
    exportItem(id: string): Promise<void>;
    remove(id: string): Promise<boolean>;
}

function sentenceOf(error: unknown, fallback: string): string {
    return error instanceof Error && error.message.trim() !== '' ? error.message : fallback;
}

export function createManagerController(
    adapter: ManagerAdapter,
    fallbackError: string,
    save: (filename: string, document: unknown) => string = downloadJson,
): ManagerController {
    let status = $state<ManagerStatus>({ kind: 'loading' });
    let items = $state<readonly ManagerItem[]>([]);
    let toggles = $state<Record<string, ManagerToggleState>>({});
    let actions = $state<Record<string, ManagerActionState>>({});
    let removed = $state<string | null>(null);
    let generation = 0;

    async function load(): Promise<void> {
        const mine = ++generation;
        status = { kind: 'loading' };
        try {
            const answer = await adapter.list();
            if (mine !== generation) return;
            items = answer;
            status = { kind: 'ready' };
        } catch (error) {
            if (mine !== generation) return;
            status = { kind: 'error', message: sentenceOf(error, fallbackError) };
        }
    }

    async function toggle(id: string, enabled: boolean): Promise<void> {
        const route = adapter.setEnabled;
        if (!route || toggles[id]?.busy) return;
        toggles = { ...toggles, [id]: { busy: true, error: null } };
        try {
            const next = await route.call(adapter, id, enabled);
            items = items.map((item) => (item.id === id ? next : item));
            toggles = { ...toggles, [id]: { busy: false, error: null } };
        } catch (error) {
            toggles = { ...toggles, [id]: { busy: false, error: sentenceOf(error, fallbackError) } };
        }
    }

    async function guard(id: string, work: () => Promise<void>): Promise<void> {
        if (toggles[id]?.busy) return;
        toggles = { ...toggles, [id]: { busy: true, error: null } };
        try {
            await work();
            toggles = { ...toggles, [id]: { busy: false, error: null } };
        } catch (error) {
            toggles = { ...toggles, [id]: { busy: false, error: sentenceOf(error, fallbackError) } };
        }
    }

    function setAction(id: string, next: ManagerActionState): void {
        actions = { ...actions, [id]: next };
    }

    async function exportItem(id: string): Promise<void> {
        const route = adapter.exportItem;
        if (!route || actions[id]?.busy) return;
        setAction(id, { busy: true, error: null, exported: null });
        try {
            const answer = await route.call(adapter, id);
            setAction(id, { busy: false, error: null, exported: save(answer.filename, answer.document) });
        } catch (error) {
            setAction(id, { busy: false, error: sentenceOf(error, fallbackError), exported: null });
        }
    }

    async function remove(id: string): Promise<boolean> {
        const route = adapter.remove;
        if (!route || actions[id]?.busy) return false;
        const name = items.find((item) => item.id === id)?.name ?? id;
        setAction(id, { busy: true, error: null, exported: null });
        try {
            await route.call(adapter, id);
        } catch (error) {
            setAction(id, { busy: false, error: sentenceOf(error, fallbackError), exported: null });
            return false;
        }
        const { [id]: _gone, ...rest } = actions;
        actions = rest;
        removed = name;
        await load();
        return true;
    }

    return {
        get status() {
            return status;
        },
        get items() {
            return items;
        },
        get toggles() {
            return toggles;
        },
        guard,
        get canToggle() {
            return typeof adapter.setEnabled === 'function';
        },
        get actions() {
            return actions;
        },
        get canExport() {
            return typeof adapter.exportItem === 'function';
        },
        get canRemove() {
            return typeof adapter.remove === 'function';
        },
        get removed() {
            return removed;
        },
        load,
        toggle,
        exportItem,
        remove,
    };
}

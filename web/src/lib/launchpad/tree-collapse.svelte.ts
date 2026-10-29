
export const TREE_COLLAPSE_KEY = 'carnivore.launchpad.collapsedProjects';

function readStored(): Set<string> {
    try {
        const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(TREE_COLLAPSE_KEY) ?? '[]');
        if (!Array.isArray(parsed)) return new Set();
        return new Set(parsed.filter((v): v is string => typeof v === 'string'));
    } catch {
        return new Set();
    }
}

function writeStored(keys: Set<string>): void {
    try {
        globalThis.localStorage?.setItem(TREE_COLLAPSE_KEY, JSON.stringify([...keys]));
    } catch {
    }
}

let collapsed = $state<Set<string> | null>(null);
let stored: Set<string> | null = null;

function current(): Set<string> {
    if (collapsed) return collapsed;
    stored ??= readStored();
    return stored;
}

export const NO_PROJECT_NODE_KEY = '__no_project__';

export const treeCollapse = {
    isCollapsed(nodeKey: string): boolean {
        return current().has(nodeKey);
    },

    set(nodeKey: string, next: boolean): void {
        if (!nodeKey) return;
        if (current().has(nodeKey) === !!next) return;
        const updated = new Set(current());
        if (next) updated.add(nodeKey);
        else updated.delete(nodeKey);
        collapsed = updated;
        writeStored(updated);
    },

    toggle(nodeKey: string): boolean {
        const next = !current().has(nodeKey);
        this.set(nodeKey, next);
        return next;
    },

    get size(): number {
        return current().size;
    },

    resetForTests(): void {
        stored = null;
        collapsed = null;
        try {
            globalThis.localStorage?.removeItem(TREE_COLLAPSE_KEY);
        } catch {
        }
    },

    simulateReloadForTests(): void {
        stored = null;
        collapsed = null;
    },
};

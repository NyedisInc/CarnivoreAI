import { companySource, type CompanySource } from './company-source.svelte';
import { projects } from '../../opscenter/api/projects.svelte';
import * as GroupStore from '../drawer/group-store';
import { COMPANIES_FOLD_KEY, GROUPS_FOLD_KEY, LAYOUT_FOLD_KEY, PROJECT_FOLD_PREFIX, SPAWNED_FOLD_SUFFIX } from '../drawer/store-keys';
import { COMPANY_ORPHANED_KEY } from '../drawer/bucketing';

export interface CascadeKeys {
    tree: string[];
    inverted: string[];
}

export interface CascadeProject {
    id: string;
    companyId: number | null;
    parentId: string | null;
}

export interface CascadeWorld {
    companyIds: number[];
    companyParent: (companyId: number) => number | null;
    projects: CascadeProject[];
    layoutKeys: string[];
    groupKeys?: string[];
}

function liveLayoutKeys(): string[] {
    const layouts = (globalThis as { SessionSidebarLayouts?: { rows?: (all: unknown[]) => { name: string }[] } }).SessionSidebarLayouts;
    return layouts && typeof layouts.rows === 'function' ? layouts.rows([]).map((r) => r.name) : [];
}

export function liveCascadeWorld(source: CompanySource = companySource()): CascadeWorld {
    const list = (projects.data ?? []).filter((p) => p.id !== null && p.id !== undefined);
    return {
        companyIds: source.companies.map((c) => c.id),
        companyParent: (id) => (source.parentOf ? source.parentOf(id) : null),
        layoutKeys: liveLayoutKeys(),
        groupKeys: GroupStore.current().groups.map((g) => GroupStore.bandKeyFor(g.group_uuid)),
        projects: list.map((p) => ({
            id: String(p.id),
            companyId: source.companyOf(String(p.id)),
            parentId: source.projectParentOf ? source.projectParentOf(String(p.id)) : null,
        })),
    };
}

function projectKeys(id: string): [string, string] {
    const key = PROJECT_FOLD_PREFIX + id;
    return [key, key + SPAWNED_FOLD_SUFFIX];
}

export function cascadeKeysFor(key: string, world: CascadeWorld): CascadeKeys {
    const tree: string[] = [];
    const inverted: string[] = [];
    const addProject = (id: string): void => {
        const [k, agents] = projectKeys(id);
        tree.push(k);
        inverted.push(agents);
    };
    if (key === COMPANIES_FOLD_KEY) {
        for (const id of world.companyIds) tree.push(`c:${id}`);
        tree.push(COMPANY_ORPHANED_KEY);
        for (const p of world.projects) addProject(p.id);
    } else if (key === GROUPS_FOLD_KEY) {
        tree.push(...(world.groupKeys ?? []));
    } else if (key === LAYOUT_FOLD_KEY) {
        inverted.push(...world.layoutKeys);
    } else if (key === COMPANY_ORPHANED_KEY) {
        const known = new Set(world.companyIds);
        for (const p of world.projects) if (p.companyId === null || !known.has(p.companyId)) addProject(p.id);
    } else if (/^c:\d+$/.test(key)) {
        const set = new Set<number>([Number(key.slice(2))]);
        let grew = true;
        while (grew) {
            grew = false;
            for (const id of world.companyIds) {
                const parent = world.companyParent(id);
                if (!set.has(id) && parent !== null && set.has(parent)) { set.add(id); grew = true; }
            }
        }
        for (const id of set) if (`c:${id}` !== key) tree.push(`c:${id}`);
        for (const p of world.projects) if (p.companyId !== null && set.has(p.companyId)) addProject(p.id);
    } else if (key.indexOf(PROJECT_FOLD_PREFIX) === 0 && !key.endsWith(SPAWNED_FOLD_SUFFIX)) {
        const rootId = key.slice(PROJECT_FOLD_PREFIX.length);
        inverted.push(key + SPAWNED_FOLD_SUFFIX);
        const seen = new Set<string>([rootId]);
        let grew = true;
        while (grew) {
            grew = false;
            for (const p of world.projects) {
                if (!seen.has(p.id) && p.parentId !== null && seen.has(p.parentId)) { seen.add(p.id); grew = true; addProject(p.id); }
            }
        }
    }
    return { tree, inverted };
}

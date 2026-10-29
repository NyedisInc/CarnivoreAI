import { companyList, companies, type Company } from '../companies';
import { projects } from '../../opscenter/api/projects.svelte';
import { repaintDrawerRows } from './interaction-globals';
import { archivedProjects, archivedShown } from '../drawer/archived-visibility';

export interface CompanySource {
    companies: Company[];
    companyOf: (projectId: string) => number | null;
    parentOf?: (companyId: number) => number | null;
    projectParentOf?: (projectId: string) => string | null;
    projectArchived?: (projectId: string) => boolean;
    projectMovedTo?: (projectId: string) => string | null;
    projectNameOf?: (projectId: string) => string | null;
    knownProjects?: readonly { id: string; name: string }[];
}

export function companySource(): CompanySource {
    const list = companyList();
    const known = new Set(list.map((c) => c.id));
    const byProject = new Map<string, number>();
    const parentProject = new Map<string, string>();
    const movedTo = new Map<string, string>();
    const names = new Map<string, string>();
    const live = new Set((projects.data ?? []).map((p) => String(p.id)));
    const archived = new Set(archivedProjects().map((p) => String(p.id)).filter((id) => !live.has(id)));
    for (const p of [...archivedProjects(), ...(projects.data ?? [])]) {
        if (p.id === null || p.id === undefined) continue;
        const id = String(p.id);
        if (p.name) names.set(id, p.name);
        if (p.company_id != null && known.has(p.company_id)) byProject.set(id, p.company_id);
        else byProject.delete(id);
        if (p.parent_project_id != null) parentProject.set(id, String(p.parent_project_id));
        else parentProject.delete(id);
        if (p.pack_state === 'moved_away') movedTo.set(id, p.moved_to_label || '');
        else movedTo.delete(id);
    }
    const parents = new Map<number, number>();
    for (const c of list) if (c.parent_id != null && known.has(c.parent_id)) parents.set(c.id, c.parent_id);
    return {
        companies: list,
        companyOf: (projectId) => byProject.get(projectId) ?? null,
        parentOf: (companyId) => parents.get(companyId) ?? null,
        projectParentOf: (projectId) => parentProject.get(projectId) ?? null,
        projectArchived: (projectId) => archived.has(projectId),
        projectMovedTo: (projectId) => (movedTo.get(projectId) ?? null),
        projectNameOf: (projectId) => names.get(projectId) ?? null,
        knownProjects: archivedShown() ? [...names].map(([id, name]) => ({ id, name })) : [],
    };
}

let stopWatching: (() => void) | null = null;

export function watchCompanies(): void {
    if (stopWatching) return;
    let first = true;
    stopWatching = $effect.root(() => {
        const signature = $derived(JSON.stringify([
            companies.list.map((c) => [c.id, c.name, c.parent_id ?? null]),
            (projects.data ?? []).map((p) => [p.id, p.name, p.company_id ?? null, p.parent_project_id ?? null, p.pack_state ?? null, p.moved_to_label ?? null, p.color ?? null]),
        ]));
        $effect(() => {
            void signature;
            if (first) { first = false; return; }
            repaintDrawerRows();
        });
    });
}

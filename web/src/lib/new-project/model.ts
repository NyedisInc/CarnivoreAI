import type { SelectChoice } from '../base/Select.svelte';
import type { TreeNode } from '../base/Tree.svelte';

export interface TreeFolder {
    name: string;
    path: string;
    project: boolean;
    company: { id: number; name: string } | null;
    children: TreeFolder[];
}

export interface FolderTree {
    root: string;
    nodes: TreeFolder[];
    truncated: boolean;
}

export interface CompanyRow {
    id: number;
    name: string;
    parent_id?: number | null;
    folder?: string | null;
}

export interface Finding {
    level: 'ok' | 'warn' | 'block';
    code: string;
    params: Record<string, string>;
}

export interface Verdict {
    ok: boolean;
    path: string;
    findings: Finding[];
}

export const NEW_COMPANY = '__new__';

export const NO_PARENT = '0';

export function slugify(name: string): string {
    return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

export function finalPath(parent: string, name: string): string {
    const slug = slugify(name);
    return parent && slug ? `${parent}/${slug}` : '';
}

export function isInside(path: string, root: string): boolean {
    return path === root || path.startsWith(`${root}/`);
}

export function relativeTo(path: string, root: string): string {
    if (path === root) return '';
    return path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path;
}

export function rootPrefix(root: string): string {
    const last = root.split('/').filter(Boolean).pop() ?? '';
    return `…/${last}/`;
}

export function ancestorPaths(path: string, root: string): string[] {
    if (!isInside(path, root) || path === root) return [];
    const parts = relativeTo(path, root).split('/');
    return parts.map((_, i) => `${root}/${parts.slice(0, i + 1).join('/')}`);
}

export function owningCompany(path: string, companies: readonly CompanyRow[]): CompanyRow | null {
    const owners = companies.filter((c) => c.folder && isInside(path, c.folder));
    return owners.reduce<CompanyRow | null>((best, c) => (!best || (c.folder ?? '').length > (best.folder ?? '').length ? c : best), null);
}

function descendants(all: readonly CompanyRow[], parent: CompanyRow, trail: string): { value: string; label: string }[] {
    const kids = all.filter((c) => c.parent_id === parent.id).sort((a, b) => a.name.localeCompare(b.name));
    return kids.flatMap((kid) => {
        const label = `${trail} > ${kid.name}`;
        return [{ value: String(kid.id), label }, ...descendants(all, kid, label)];
    });
}

export function companyChoices(companies: readonly CompanyRow[], parentSelf: (name: string) => string): SelectChoice[] {
    const known = new Set(companies.map((c) => c.id));
    const tops = companies.filter((c) => !c.parent_id || !known.has(c.parent_id)).sort((a, b) => a.name.localeCompare(b.name));
    return tops.map((top): SelectChoice => {
        const below = descendants(companies, top, top.name);
        if (below.length === 0) return { value: String(top.id), label: top.name };
        return { group: top.name, options: [{ value: String(top.id), label: parentSelf(top.name) }, ...below] };
    });
}

export function toTreeNodes(folders: readonly TreeFolder[], root: string, filter: string): TreeNode[] {
    const term = filter.trim().toLowerCase();
    const walk = (list: readonly TreeFolder[]): TreeNode[] =>
        list.flatMap((folder) => {
            const kids = walk(folder.children);
            const hit = relativeTo(folder.path, root).toLowerCase().includes(term);
            if (term && !hit && kids.length === 0) return [];
            return [{ id: folder.path, label: folder.name, data: folder, ...(kids.length ? { children: kids } : {}) }];
        });
    return walk(folders);
}

export function companyFolderFor(typed: string, parentFolder: string | null, root: string, name: string): string {
    const text = typed.trim().replace(/\/+$/, '');
    if (text) return text.startsWith('/') ? text : `${root}/${text}`;
    const slug = slugify(name);
    return slug ? `${parentFolder ?? root}/${slug}` : '';
}

import type { ProjectRow } from '../sessions/types';

export interface AddProject {
    path: string;
    name: string;
}

function within(root: string, dir: string): boolean {
    const bare = root.replace(/\/+$/, '');
    return dir === bare || dir.startsWith(`${bare}/`);
}

export function addProjectsOf(rows: readonly ProjectRow[], viewedDir: string | null): AddProject[] {
    const out: AddProject[] = [];
    for (const row of rows) {
        const path = typeof row.path === 'string' && row.path ? row.path : typeof row.root === 'string' ? row.root : '';
        if (!path) continue;
        const name = (typeof row.name === 'string' && row.name.trim()) || path.split('/').filter(Boolean).pop() || path;
        out.push({ path, name });
    }
    if (!viewedDir) return out;
    let best = -1;
    out.forEach((project, index) => {
        if (within(project.path, viewedDir) && (best < 0 || project.path.length > out[best].path.length)) best = index;
    });
    if (best > 0) out.unshift(...out.splice(best, 1));
    return out;
}

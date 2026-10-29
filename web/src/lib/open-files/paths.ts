
function trimSlash(path: string): string {
    const trimmed = path.replace(/\/+$/, '');
    return trimmed === '' && path.startsWith('/') ? '/' : trimmed;
}

export function workdirRelative(path: string, repoRoot: string | null | undefined, workdirReal: string | null | undefined): string | null {
    if (!path || !repoRoot || !workdirReal || path.startsWith('/')) return null;
    const root = trimSlash(repoRoot);
    const work = trimSlash(workdirReal);
    if (root === work) return path;
    const full = `${root === '/' ? '' : root}/${path}`;
    const prefix = `${work === '/' ? '' : work}/`;
    return full.startsWith(prefix) && full.length > prefix.length ? full.slice(prefix.length) : null;
}

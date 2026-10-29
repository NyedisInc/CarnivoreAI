import type { SessionGitFile } from '../../opscenter/api/types';

export type GitTone = 'green' | 'yellow' | 'coral';

export interface GitTag {
    letter: string;
    tone: GitTone;
    kind: SessionGitFile['kind'] | 'folder';
}

export const GIT_LETTERS: Record<SessionGitFile['kind'], string> = {
    untracked: 'U', modified: 'M', added: 'A', deleted: 'D', renamed: 'R', copied: 'C', typechange: 'T', conflicted: '!',
};

export const GIT_TONES: Record<SessionGitFile['kind'], GitTone> = {
    untracked: 'green', added: 'green', copied: 'green',
    modified: 'yellow', renamed: 'yellow', typechange: 'yellow',
    deleted: 'coral', conflicted: 'coral',
};

export const FOLDER_MARK = '•';

const STRENGTH: Record<GitTone, number> = { green: 1, yellow: 2, coral: 3 };

export interface GitTagIndex {
    files: Map<string, GitTag>;
    folders: Map<string, GitTone>;
    untrackedDirs: string[];
}

function trimDir(path: string): string {
    return path.length > 1 ? path.replace(/\/+$/, '') : path;
}

export function treePathOf(repoPath: string, repoRoot: string, workdir: string): string | null {
    const root = trimDir(repoRoot);
    const dir = trimDir(workdir);
    if (!root || !dir) return null;
    if (dir === root) return repoPath;
    if (dir.startsWith(`${root}/`)) {
        const prefix = `${dir.slice(root.length + 1)}/`;
        return repoPath.startsWith(prefix) && repoPath.length > prefix.length ? repoPath.slice(prefix.length) : null;
    }
    if (root.startsWith(`${dir}/`)) return `${root.slice(dir.length + 1)}/${repoPath}`;
    return null;
}

export function buildGitTags(files: readonly SessionGitFile[], repoRoot: string, workdir: string): GitTagIndex {
    const index: GitTagIndex = { files: new Map(), folders: new Map(), untrackedDirs: [] };
    for (const file of files) {
        const mapped = treePathOf(file.path, repoRoot, workdir);
        if (mapped === null) continue;
        const isDirEntry = mapped.endsWith('/');
        const path = isDirEntry ? mapped.replace(/\/+$/, '') : mapped;
        if (!path) continue;
        const tone = GIT_TONES[file.kind];
        if (isDirEntry && file.kind === 'untracked') index.untrackedDirs.push(path);
        else index.files.set(path, { letter: GIT_LETTERS[file.kind], tone, kind: file.kind });
        const parts = path.split('/');
        for (let i = 1; i < parts.length; i++) {
            const folder = parts.slice(0, i).join('/');
            const held = index.folders.get(folder);
            if (!held || STRENGTH[tone] > STRENGTH[held]) index.folders.set(folder, tone);
        }
    }
    return index;
}

export function gitTagFor(index: GitTagIndex, path: string, isDir: boolean): GitTag | null {
    const own = index.files.get(path);
    if (own) return own;
    if (index.untrackedDirs.some((dir) => path === dir || path.startsWith(`${dir}/`))) {
        return { letter: GIT_LETTERS.untracked, tone: GIT_TONES.untracked, kind: 'untracked' };
    }
    if (!isDir) return null;
    const tone = index.folders.get(path);
    return tone ? { letter: FOLDER_MARK, tone, kind: 'folder' } : null;
}

export function applyGitTags(tree: ParentNode, index: GitTagIndex | null): number {
    let tagged = 0;
    for (const row of tree.querySelectorAll<HTMLElement>('[data-root="workdir"][data-path]')) {
        const path = row.dataset.path ?? '';
        const tag = index && path ? gitTagFor(index, path, row.classList.contains('config-editor-toggle')) : null;
        if (tag) tagged += 1;
        setAttr(row, 'data-git-tone', tag?.tone ?? null);
        setAttr(row, 'data-git-letter', tag?.letter ?? null);
        setAttr(row, 'data-git-kind', tag?.kind ?? null);
    }
    return tagged;
}

function setAttr(el: HTMLElement, name: string, value: string | null): void {
    if (value === null) {
        if (el.hasAttribute(name)) el.removeAttribute(name);
    } else if (el.getAttribute(name) !== value) {
        el.setAttribute(name, value);
    }
}

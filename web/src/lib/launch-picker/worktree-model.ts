import { authFetch } from '../../opscenter/api/auth.svelte';

export interface CopyCandidate { name: string; secret: boolean }

export interface WorktreeProbe {
    repo: boolean;
    toplevel?: string;
    branches?: string[];
    current?: string | null;
    file?: { sha256: string; setup: string[][]; copy: CopyCandidate[]; approved: boolean; text: string } | null;
    file_error?: string | null;
}

export interface WorktreeAnswer { branch: string; base_branch: string | null; setup: boolean; copy: string[] }

type Fetcher = typeof authFetch;

export function createWorktreeApi(f: Fetcher = authFetch) {
    return {
        probe: (folder: string) => f<WorktreeProbe>(`/worktrees/probe?folder=${encodeURIComponent(folder)}`),
        approve: (repo: string, sha256: string) => f<{ approved: boolean; sha256: string }>('/worktrees/setup/approve', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo, sha256 }),
        }),
    };
}
export type WorktreeApi = ReturnType<typeof createWorktreeApi>;

export function branchFromName(name: string): string {
    const slug = name.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 60);
    return slug ? `wt/${slug}` : '';
}

export function initialCopy(probe: WorktreeProbe | null): string[] {
    return (probe?.file?.copy ?? []).filter((c) => !c.secret).map((c) => c.name);
}

export function worktreeAnswer(on: boolean, branch: string, base: string, setup: boolean, copy: readonly string[]): WorktreeAnswer | null {
    const b = branch.trim();
    if (!on || !b) return null;
    return { branch: b, base_branch: base.trim() || null, setup, copy: [...copy] };
}

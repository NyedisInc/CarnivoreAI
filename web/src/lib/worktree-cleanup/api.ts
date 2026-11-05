import { authFetch } from '../../opscenter/api/auth.svelte';

export interface WorktreeRow { path: string; repo: string; branch: string; base_branch: string; sessions: { id: string; tmux: string | null }[] }

export interface PlannedWorktree {
    path: string; repo: string; branch: string; base_branch: string; exists: boolean; head: string | null;
    dirty: string[]; untracked: number; merged: boolean; unmerged_commits: number; pushed: boolean | null;
    finished: boolean; steps: string[];
}

export interface CleanupPlan { worktrees: PlannedWorktree[]; fingerprint: string }

export interface CleanupResult { path: string; removed: boolean; branch_deleted: boolean; error: string | null }

export interface CleanupScope { paths?: string[]; finishedOnly?: boolean }

const JSON_HEADERS = { 'Content-Type': 'application/json' };

let rows: WorktreeRow[] = [];
let inflight: Promise<void> | null = null;
let loaded = false;

export function refreshWorktrees(): Promise<void> {
    if (inflight) return inflight;
    inflight = authFetch<{ worktrees: WorktreeRow[] }>('/worktrees')
        .then((r) => { rows = Array.isArray(r?.worktrees) ? r.worktrees : rows; })
        .catch(() => undefined)
        .finally(() => { loaded = true; inflight = null; });
    return inflight;
}

export function worktreeForSession(sessionId: string | null, tmuxName: string): WorktreeRow | null {
    void refreshWorktrees();
    if (!loaded) return null;
    return rows.find((w) => w.sessions.some((s) => (sessionId && s.id === sessionId) || (tmuxName && s.tmux === tmuxName))) ?? null;
}

export function planCleanup(scope: CleanupScope): Promise<CleanupPlan> {
    return authFetch<CleanupPlan>('/worktrees/cleanup', { method: 'POST', headers: JSON_HEADERS,
        body: JSON.stringify({ paths: scope.paths ?? null, finished_only: !!scope.finishedOnly, apply: false }) });
}

export async function applyCleanup(plan: CleanupPlan, deleteUnmerged: boolean, removeDirty: boolean): Promise<{ removed: CleanupResult[] }> {
    const out = await authFetch<{ removed: CleanupResult[] }>('/worktrees/cleanup', { method: 'POST', headers: JSON_HEADERS,
        body: JSON.stringify({ paths: plan.worktrees.map((w) => w.path), apply: true, fingerprint: plan.fingerprint,
            delete_unmerged: deleteUnmerged, remove_dirty: removeDirty }) });
    void refreshWorktrees();
    return out;
}

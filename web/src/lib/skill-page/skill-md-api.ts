import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { Fetcher, SkillsContext } from '../skills-page/skills-api';

export interface SkillMdRead {
    readonly location_id: string;
    readonly name: string;
    readonly body: string;
    readonly body_truncated: boolean;
    readonly size: number;
    readonly sha256: string;
}

export interface SkillMdVersion {
    readonly id: number;
    readonly created_at: number;
    readonly redacted?: boolean;
    readonly note: string | null;
    readonly sha256: string;
    readonly size: number;
    readonly lines?: number;
    readonly action: 'edit' | 'restore' | 'baseline';
}

export interface SkillMdVersionList {
    readonly versions: SkillMdVersion[];
    readonly current: SkillMdVersion | null;
}

export interface SkillMdWritten {
    readonly sha256: string;
    readonly version_id: number;
}

/* the file changed on disk */
export class StaleBaseError extends Error {
    constructor(readonly currentSha256: string | null) {
        super('the file changed on disk');
        this.name = 'StaleBaseError';
    }
}

function query(context: SkillsContext): string {
    const parts: string[] = [];
    if (context.projectPath) parts.push(`project_path=${encodeURIComponent(context.projectPath)}`);
    if (context.profile) parts.push(`profile=${encodeURIComponent(context.profile)}`);
    return parts.length > 0 ? `?${parts.join('&')}` : '';
}

function staleHash(error: unknown): string | null | undefined {
    if (!(error instanceof ApiError) || error.status !== 409) return undefined;
    const payload = error.payload as { current_sha256?: unknown; detail?: { code?: unknown; current_sha256?: unknown } } | null;
    const found = payload?.current_sha256 ?? payload?.detail?.current_sha256;
    if (typeof found === 'string') return found;
    return payload?.detail?.code === 'stale' ? null : undefined;
}

async function guarded(run: () => Promise<SkillMdWritten>): Promise<SkillMdWritten> {
    try {
        return await run();
    } catch (error) {
        const stale = staleHash(error);
        if (stale !== undefined) throw new StaleBaseError(stale);
        throw error;
    }
}

const base = (locationId: string): string => `/skills/locations/${encodeURIComponent(locationId)}/skill-md`;

export function readSkillMd(locationId: string, context: SkillsContext, fetcher: Fetcher = authFetch): Promise<SkillMdRead> {
    return fetcher<SkillMdRead>(`${base(locationId)}${query(context)}`);
}

export function saveSkillMd(
    locationId: string,
    content: string,
    baseSha256: string,
    note: string | null,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<SkillMdWritten> {
    const body: Record<string, unknown> = { content, base_sha256: baseSha256 };
    if (note) body['note'] = note;
    return guarded(() => fetcher<SkillMdWritten>(`${base(locationId)}${query(context)}`, { method: 'PUT', body: JSON.stringify(body) }));
}

export async function listSkillMdVersions(locationId: string, context: SkillsContext, fetcher: Fetcher = authFetch): Promise<SkillMdVersionList> {
    const answer = await fetcher<{ versions?: SkillMdVersion[]; current?: SkillMdVersion | null }>(`${base(locationId)}/versions${query(context)}`);
    return { versions: Array.isArray(answer.versions) ? answer.versions : [], current: answer.current ?? null };
}

export function readSkillMdVersion(
    locationId: string,
    versionId: number,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<{ content: string; sha256: string }> {
    return fetcher(`${base(locationId)}/versions/${encodeURIComponent(String(versionId))}${query(context)}`);
}

export function restoreSkillMdVersion(
    locationId: string,
    versionId: number,
    baseSha256: string,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<SkillMdWritten> {
    const body: Record<string, unknown> = { base_sha256: baseSha256 };
    return guarded(() => fetcher<SkillMdWritten>(`${base(locationId)}/versions/${encodeURIComponent(String(versionId))}/restore${query(context)}`, { method: 'POST', body: JSON.stringify(body) }));
}

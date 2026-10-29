import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type { CatalogHost } from '../catalog/catalog';
import type {
    CatalogContents,
    CatalogItem,
    CatalogItemResponse,
    InstalledItem,
    InstalledListResponse,
    SkillAutopsy,
    SkillUsage,
} from '../catalog/types';
import type { Census, Inventory, OverrideFile, OverrideResult, SessionSkills } from './skills-types';

export type Fetcher = typeof authFetch;

export interface SkillsContext {
    readonly projectPath: string | null;
    readonly profile: string | null;
}

function query(context: SkillsContext): string {
    const parts: string[] = [];
    if (context.projectPath) parts.push(`project_path=${encodeURIComponent(context.projectPath)}`);
    if (context.profile) parts.push(`profile=${encodeURIComponent(context.profile)}`);
    return parts.length > 0 ? `?${parts.join('&')}` : '';
}

export function refusalOf(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        const body = error.payload as { detail?: unknown } | null;
        const detail = body?.detail;
        if (typeof detail === 'string' && detail.trim() !== '') return detail;
        if (detail && typeof detail === 'object') {
            const inner = (detail as { detail?: unknown }).detail;
            if (typeof inner === 'string' && inner.trim() !== '') return inner;
        }
    }
    return error instanceof Error && error.message.trim() !== '' ? error.message : fallback;
}

export function refusalCode(error: unknown): string | null {
    if (!(error instanceof ApiError)) return null;
    const detail = (error.payload as { detail?: unknown } | null)?.detail;
    if (detail && typeof detail === 'object') {
        const code = (detail as { code?: unknown }).code;
        if (typeof code === 'string') return code;
    }
    return error.code;
}

export function fetchInventory(context: SkillsContext, fetcher: Fetcher = authFetch): Promise<Inventory> {
    return fetcher<Inventory>(`/skills${query(context)}`);
}

export interface OverrideRequest {
    readonly harness: 'claude' | 'codex';
    readonly file: OverrideFile;
    readonly skill: string;
    readonly state: string | null;
    readonly projectPath?: string | null;
    readonly profile?: string | null;
}

export function putOverride(request: OverrideRequest, fetcher: Fetcher = authFetch): Promise<OverrideResult> {
    const body: Record<string, unknown> = {
        harness: request.harness,
        file: request.file,
        skill: request.skill,
        state: request.state,
    };
    if (request.projectPath) body['project_path'] = request.projectPath;
    if (request.profile) body['profile'] = request.profile;
    return fetcher<OverrideResult>('/skills/overrides', { method: 'PUT', body: JSON.stringify(body) });
}

export async function removeLocation(
    locationId: string,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<void> {
    const body: Record<string, unknown> = { confirm: true };
    if (context.projectPath) body['project_path'] = context.projectPath;
    if (context.profile) body['profile'] = context.profile;
    await fetcher(`/skills/locations/${encodeURIComponent(locationId)}`, {
        method: 'DELETE',
        body: JSON.stringify(body),
    });
}

export async function regenerateCardArt(
    locationId: string,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<boolean> {
    const body: Record<string, unknown> = {};
    if (context.projectPath) body['project_path'] = context.projectPath;
    if (context.profile) body['profile'] = context.profile;
    const reply = await fetcher<{ queued?: boolean }>(`/skills/locations/${encodeURIComponent(locationId)}/card-art/regenerate`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
    return reply?.queued === true;
}

export interface LocalSkillMd {
    readonly location_id: string;
    readonly name: string;
    readonly body: string;
    readonly body_truncated: boolean;
    readonly size: number;
}

export function fetchLocationSkillMd(
    locationId: string,
    context: SkillsContext,
    fetcher: Fetcher = authFetch,
): Promise<LocalSkillMd> {
    return fetcher<LocalSkillMd>(`/skills/locations/${encodeURIComponent(locationId)}/skill-md${query(context)}`);
}

export function fetchSessionSkills(sessionId: string, fetcher: Fetcher = authFetch): Promise<SessionSkills> {
    return fetcher<SessionSkills>(`/sessions/${encodeURIComponent(sessionId)}/skills`);
}

export function fetchCensus(context: SkillsContext, fetcher: Fetcher = authFetch): Promise<Census> {
    return fetcher<Census>(`/skills/census${query(context)}`);
}

export async function fetchLedger(fetcher: Fetcher = authFetch): Promise<InstalledItem[] | null> {
    try {
        const answer = await fetcher<InstalledListResponse>('/catalog/installed');
        return Array.isArray(answer.items) ? answer.items : [];
    } catch {
        return null;
    }
}

export async function fetchCatalogEntry(itemId: string, fetcher: Fetcher = authFetch): Promise<CatalogItem | null> {
    try {
        const answer = await fetcher<CatalogItemResponse>(`/catalog/items/${encodeURIComponent(itemId)}`);
        return answer.item ?? null;
    } catch {
        return null;
    }
}

export function skillHost(fetcher: Fetcher = authFetch): Pick<CatalogHost, 'skillUsage' | 'skillAutopsy' | 'contents'> {
    return {
        skillUsage: (skill) => fetcher<SkillUsage>(`/skill-fires/usage?skill=${encodeURIComponent(skill)}`),
        skillAutopsy: (skill) => fetcher<SkillAutopsy>(`/skills/${encodeURIComponent(skill)}/autopsy?days=30`),
        contents: (itemId) => fetcher<CatalogContents>(`/catalog/contents/${encodeURIComponent(itemId)}`),
    };
}

export function restoreInstall(installId: string, revision: number, fetcher: Fetcher = authFetch): Promise<InstalledItem> {
    return fetcher<InstalledItem>(`/catalog/installed/${encodeURIComponent(installId)}/restore`, {
        method: 'POST',
        body: JSON.stringify({ expected_revision: revision }),
    });
}

export function setInstallFork(installId: string, forked: boolean, fetcher: Fetcher = authFetch): Promise<InstalledItem> {
    return fetcher<InstalledItem>(`/catalog/installed/${encodeURIComponent(installId)}/fork`, {
        method: 'PUT',
        body: JSON.stringify({ forked }),
    });
}

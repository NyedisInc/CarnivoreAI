import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type {
    Blueprint,
    BlueprintError,
    BlueprintList,
    BlueprintSpec,
    LaunchPreviewResponse,
    LaunchResponse,
    SkillConsent,
    WorktreeSettings,
} from './types';

const ROOT = '/blueprints';

export function blueprintError(error: unknown): BlueprintError {
    if (!(error instanceof ApiError)) {
        return { code: '', detail: error instanceof Error ? error.message : String(error), status: 0, detectors: [] };
    }
    const body = error.payload as { detail?: unknown } | null;
    const rawDetail = body?.detail;
    if (Array.isArray(rawDetail)) {
        const msgs = rawDetail
            .map((entry) =>
                entry && typeof entry === 'object' && typeof (entry as { msg?: unknown }).msg === 'string'
                    ? (entry as { msg: string }).msg
                    : null,
            )
            .filter((msg): msg is string => !!msg);
        return {
            code: error.code ?? '',
            detail: msgs.length > 0 ? msgs.join('; ') : error.message,
            status: error.status,
            detectors: [],
        };
    }
    const inner = rawDetail && typeof rawDetail === 'object' ? (rawDetail as Record<string, unknown>) : {};
    const detectors = Array.isArray(inner['detectors'])
        ? (inner['detectors'] as unknown[]).filter((d): d is string => typeof d === 'string')
        : [];
    return {
        code: typeof inner['code'] === 'string' ? (inner['code'] as string) : error.code ?? '',
        detail: typeof inner['detail'] === 'string' ? (inner['detail'] as string) : error.message,
        status: error.status,
        detectors,
    };
}

export function listBlueprints(): Promise<BlueprintList> {
    return authFetch<BlueprintList>(ROOT);
}

export function getBlueprint(uuid: string): Promise<Blueprint> {
    return authFetch<Blueprint>(`${ROOT}/${encodeURIComponent(uuid)}`);
}

export function createBlueprint(spec: BlueprintSpec): Promise<Blueprint> {
    return authFetch<Blueprint>(ROOT, { method: 'POST', body: JSON.stringify({ spec }) });
}

export function updateBlueprint(uuid: string, spec: BlueprintSpec): Promise<Blueprint> {
    return authFetch<Blueprint>(`${ROOT}/${encodeURIComponent(uuid)}`, {
        method: 'PUT',
        body: JSON.stringify({ spec }),
    });
}

export function deleteBlueprint(uuid: string): Promise<{ deleted: boolean }> {
    return authFetch<{ deleted: boolean }>(`${ROOT}/${encodeURIComponent(uuid)}`, { method: 'DELETE' });
}

export function blueprintFromLayout(layoutUuid: string, name?: string): Promise<Blueprint> {
    return authFetch<Blueprint>(`${ROOT}/from-layout/${encodeURIComponent(layoutUuid)}`, {
        method: 'POST',
        body: JSON.stringify(name ? { name } : {}),
    });
}

export function exportBlueprint(uuid: string, projectPath: string): Promise<{ path: string; blueprint_uuid: string }> {
    return authFetch<{ path: string; blueprint_uuid: string }>(`${ROOT}/${encodeURIComponent(uuid)}/export`, {
        method: 'POST',
        body: JSON.stringify({ project_path: projectPath }),
    });
}

export function importBlueprint(projectPath: string, name?: string): Promise<Blueprint> {
    return authFetch<Blueprint>(`${ROOT}/import`, {
        method: 'POST',
        body: JSON.stringify(name ? { project_path: projectPath, name } : { project_path: projectPath }),
    });
}

export function getWorktreeSettings(): Promise<WorktreeSettings> {
    return authFetch<WorktreeSettings>(`${ROOT}/settings`);
}

export function setWorktreeSettings(worktreeRoot: string): Promise<WorktreeSettings> {
    return authFetch<WorktreeSettings>(`${ROOT}/settings`, {
        method: 'PUT',
        body: JSON.stringify({ worktree_root: worktreeRoot }),
    });
}

export function previewLaunch(uuid: string, members?: number[]): Promise<LaunchPreviewResponse> {
    return authFetch<LaunchPreviewResponse>(`${ROOT}/${encodeURIComponent(uuid)}/launch/preview`, {
        method: 'POST',
        body: JSON.stringify(members ? { members } : {}),
    });
}

export function launchBlueprint(
    uuid: string,
    options: { consents?: Record<string, SkillConsent>; members?: number[]; overwriteLayout?: boolean } = {},
): Promise<LaunchResponse> {
    return authFetch<LaunchResponse>(`${ROOT}/${encodeURIComponent(uuid)}/launch`, {
        method: 'POST',
        body: JSON.stringify({
            consents: options.consents ?? {},
            ...(options.members ? { members: options.members } : {}),
            ...(options.overwriteLayout ? { overwrite_layout: true } : {}),
        }),
    });
}

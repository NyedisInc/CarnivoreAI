import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import type {
    CreateWorkspaceRequest,
    CreateWorkspaceResponse,
    DeleteWorkspaceResponse,
    DevStartRequest,
    DevStartResponse,
    DevStopResponse,
    InstallWorkspaceRequest,
    InstallWorkspaceResult,
    LaunchAgentRequest,
    LaunchedSession,
    PreviewRenderRequest,
    PreviewRenderResponse,
    PublishWorkspaceRequest,
    PublishWorkspaceResult,
    ReadinessReport,
    RunReadinessRequest,
    SandboxTestReport,
    StudioActionError,
    StudioWorkspace,
    TestSandboxRequest,
    WorkspaceDetailResponse,
} from './types';

export type StudioFetcher = typeof authFetch;

function asRecord(value: unknown): Record<string, unknown> | null {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Record<string, unknown> => asRecord(item) !== null);
}

export function extractStudioError(err: unknown): StudioActionError {
    if (err instanceof ApiError) {
        const payload = asRecord(err.payload);
        const nestedDetail = asRecord(payload?.detail);
        const code =
            (typeof nestedDetail?.code === 'string' && nestedDetail.code) ||
            (typeof payload?.code === 'string' && payload.code) ||
            err.code ||
            'studio_error';
        const message =
            (typeof nestedDetail?.detail === 'string' && nestedDetail.detail) ||
            (typeof nestedDetail?.message === 'string' && nestedDetail.message) ||
            (typeof payload?.detail === 'string' && payload.detail) ||
            err.message ||
            code;
        const refusals = asRecordArray(nestedDetail?.refusals ?? payload?.refusals);
        return {
            code,
            message,
            status: err.status,
            refusals,
            details: nestedDetail ?? payload,
        };
    }
    if (err instanceof Error) {
        return {
            code: 'studio_error',
            message: err.message || 'studio_error',
            status: 0,
            refusals: [],
            details: null,
        };
    }
    return {
        code: 'studio_error',
        message: typeof err === 'string' && err ? err : 'studio_error',
        status: 0,
        refusals: [],
        details: null,
    };
}

function enc(studioId: string): string {
    return encodeURIComponent(studioId);
}

export async function listWorkspaces(fetcher: StudioFetcher = authFetch): Promise<StudioWorkspace[]> {
    const data = await fetcher<{ workspaces?: StudioWorkspace[] }>('/cplug-owner/studio/workspaces');
    return Array.isArray(data?.workspaces) ? data.workspaces : [];
}

export async function createWorkspace(
    body: CreateWorkspaceRequest,
    fetcher: StudioFetcher = authFetch,
): Promise<CreateWorkspaceResponse> {
    return await fetcher<CreateWorkspaceResponse>('/cplug-owner/studio/workspaces', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function getWorkspace(
    studioId: string,
    fetcher: StudioFetcher = authFetch,
): Promise<WorkspaceDetailResponse> {
    return await fetcher<WorkspaceDetailResponse>(`/cplug-owner/studio/workspaces/${enc(studioId)}`);
}

export async function deleteWorkspace(
    studioId: string,
    deleteFiles = true,
    fetcher: StudioFetcher = authFetch,
): Promise<DeleteWorkspaceResponse> {
    const qs = deleteFiles ? '?delete_files=true' : '?delete_files=false';
    return await fetcher<DeleteWorkspaceResponse>(`/cplug-owner/studio/workspaces/${enc(studioId)}${qs}`, {
        method: 'DELETE',
    });
}

export async function launchAgent(
    studioId: string,
    body: LaunchAgentRequest = {},
    fetcher: StudioFetcher = authFetch,
): Promise<LaunchedSession> {
    return await fetcher<LaunchedSession>(`/cplug-owner/studio/workspaces/${enc(studioId)}/agent`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function startDev(
    studioId: string,
    body: DevStartRequest = { auto_approve: true },
    fetcher: StudioFetcher = authFetch,
): Promise<DevStartResponse> {
    return await fetcher<DevStartResponse>(`/cplug-owner/studio/workspaces/${enc(studioId)}/dev/start`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function stopDev(
    studioId: string,
    fetcher: StudioFetcher = authFetch,
): Promise<DevStopResponse> {
    return await fetcher<DevStopResponse>(`/cplug-owner/studio/workspaces/${enc(studioId)}/dev/stop`, {
        method: 'POST',
    });
}

export async function getReadiness(
    studioId: string,
    runTests = false,
    fetcher: StudioFetcher = authFetch,
): Promise<ReadinessReport> {
    const qs = runTests ? '?run_tests=true' : '?run_tests=false';
    return await fetcher<ReadinessReport>(`/cplug-owner/studio/workspaces/${enc(studioId)}/readiness${qs}`);
}

export async function runReadiness(
    studioId: string,
    body: RunReadinessRequest = { run_tests: true },
    fetcher: StudioFetcher = authFetch,
): Promise<ReadinessReport> {
    return await fetcher<ReadinessReport>(`/cplug-owner/studio/workspaces/${enc(studioId)}/readiness`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function testSandbox(
    studioId: string,
    body: TestSandboxRequest = {},
    fetcher: StudioFetcher = authFetch,
): Promise<SandboxTestReport> {
    return await fetcher<SandboxTestReport>(`/cplug-owner/studio/workspaces/${enc(studioId)}/test-sandbox`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function installWorkspace(
    studioId: string,
    body: InstallWorkspaceRequest = { activate_runtime: true, auto_approve: true },
    fetcher: StudioFetcher = authFetch,
): Promise<InstallWorkspaceResult> {
    return await fetcher<InstallWorkspaceResult>(`/cplug-owner/studio/workspaces/${enc(studioId)}/install`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function publishWorkspace(
    studioId: string,
    body: PublishWorkspaceRequest,
    fetcher: StudioFetcher = authFetch,
): Promise<PublishWorkspaceResult> {
    return await fetcher<PublishWorkspaceResult>(`/cplug-owner/studio/workspaces/${enc(studioId)}/publish`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export async function previewRender(
    studioId: string,
    body: PreviewRenderRequest = {},
    fetcher: StudioFetcher = authFetch,
): Promise<PreviewRenderResponse> {
    return await fetcher<PreviewRenderResponse>(`/cplug-owner/studio/workspaces/${enc(studioId)}/preview-render`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

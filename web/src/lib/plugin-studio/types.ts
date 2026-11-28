import type { PluginInspectorSnapshot } from '../plugins/store.svelte';

export type StudioTemplate =
    | 'no-code'
    | 'python'
    | 'typescript'
    | 'bash'
    | 'widget'
    | 'channel'
    | 'agent-harness';

export type StudioBusyAction =
    | 'list'
    | 'create'
    | 'detail'
    | 'delete'
    | 'agent'
    | 'dev'
    | 'preview'
    | 'readiness'
    | 'sandbox'
    | 'install'
    | 'publish'
    | null;

export type StudioAgentKind = 'claude' | 'codex' | 'agy';

export type ReadinessStatus = 'pass' | 'fail' | 'advisory' | 'undetermined' | 'unavailable';

export interface StudioWorkspace {
    studio_id: string;
    plugin_id: string;
    name: string;
    template: StudioTemplate;
    prompt: string;
    agent_kind: StudioAgentKind;
    folder: string;
    session_id: string | null;
    session_tmux: string | null;
    dev_active: boolean;
    created_at: string;
    updated_at: string;
    last_readiness: ReadinessReport | null;
}

export interface WorkspaceFile {
    path: string;
    size: number;
    executable: boolean;
}

export interface SessionStatus {
    session_id: string | null;
    active: boolean;
    status: string;
    tmux_session?: string | null;
}

export interface LaunchedSession {
    session_id: string;
    tmux_session: string | null;
    agent_kind: StudioAgentKind | string;
    agent_type: string;
    opening_prompt: string;
}

export interface DevTrustLease {
    plugin_id: string;
    install_key?: string;
    baseline_sha: string;
    expires_at: string;
    ttl_seconds?: number;
}

export interface DevStatus {
    active: boolean;
    plugin_id: string;
    status: string;
    reload_count: number;
    last_reload_ms: number | null;
    last_error: string | Record<string, unknown> | null;
    lease: DevTrustLease | null;
}

export interface DevStartResponse {
    active: boolean;
    plugin_id: string;
    lease: DevTrustLease;
}

export interface DevStopResponse {
    active: boolean;
}

export interface StudioDeclaredCapabilities {
    permissions: string[];
    permission_reasons: Record<string, string>;
    tools: string[];
    routes: string[];
    views: string[];
    ui_slots: string[];
    services_provides: string[];
    services_consumes: string[];
    events_emit: string[];
    events_on: string[];
}

export interface StudioInspectorSnapshot extends PluginInspectorSnapshot {
    studio_id: string;
    dev: DevStatus;
    capabilities: StudioDeclaredCapabilities;
    events: Array<Record<string, unknown>>;
    ui_errors: Array<Record<string, unknown>>;
    slot_renders: Record<string, Array<Record<string, unknown>>> | Array<Record<string, unknown>>;
}

export interface PreviewValidationError {
    code: string;
    detail?: string;
    path?: string;
}

export interface PreviewRenderResponse {
    kind: 'view' | 'declarative' | 'none' | 'error';
    surface?: string;
    view_url: string | null;
    doc: unknown | null;
    theme_id: string | null;
    width: number | null;
    height: number | null;
    errors: PreviewValidationError[];
}

export interface ReadinessItem {
    id: string;
    label: string;
    category: string;
    status: ReadinessStatus;
    code: string;
    detail: string;
    findings: Array<Record<string, unknown>>;
}

export interface ReadinessSummary {
    pass: number;
    fail: number;
    advisory: number;
    undetermined: number;
    unavailable: number;
}

export interface ReadinessReport {
    ok: boolean;
    ready: boolean;
    items: ReadinessItem[];
    checked_at: string;
    digest: string;
    summary: ReadinessSummary;
}

export interface SandboxTestReport {
    ok: boolean;
    check: {
        ok: boolean;
        warnings: string[];
    };
    unit: {
        output: string;
        ok?: boolean;
    };
    smoke: Record<string, unknown> | null;
    errors: string[];
    warnings: string[];
}

export interface InstallWorkspaceResult {
    ok: boolean;
    plugin_id: string;
    item_id: string;
    enabled: boolean;
    runtime_active: boolean;
    digest: string;
}

export type PublishMode = 'local' | 'github';

export interface PublishWorkspaceRequest {
    mode?: PublishMode;
    repo?: string | null;
    tag?: string | null;
    pointer?: string | null;
    commit_sha?: string | null;
    subdir?: string | null;
    version?: string | null;
    digest?: string | null;
    dry_run?: boolean;
    include_workspace_files?: boolean;
}

export interface PublishWorkspaceResult {
    ok: boolean;
    dry_run: boolean;
    preview: Record<string, unknown> | null;
    submission: Record<string, unknown> | null;
}

export interface CreateWorkspaceRequest {
    prompt: string;
    name?: string | null;
    template?: StudioTemplate;
    agent_kind?: StudioAgentKind;
    start_agent?: boolean;
    start_dev?: boolean;
    author?: string | null;
}

export interface CreateWorkspaceResponse {
    workspace: StudioWorkspace;
    files: WorkspaceFile[];
    session: LaunchedSession | null;
    dev: DevStartResponse | null;
}

export interface WorkspaceDetailResponse {
    workspace: StudioWorkspace;
    files: WorkspaceFile[];
    session_status: SessionStatus;
    dev_status: DevStatus;
    inspector: StudioInspectorSnapshot;
    preview: PreviewRenderResponse;
}

export interface DeleteWorkspaceResponse {
    ok: boolean;
    studio_id: string;
}

export interface LaunchAgentRequest {
    agent_kind?: StudioAgentKind;
    prompt?: string | null;
}

export interface DevStartRequest {
    auto_approve?: boolean;
}

export interface RunReadinessRequest {
    run_tests?: boolean;
    handle?: string | null;
}

export interface TestSandboxRequest {
    unit_only?: boolean;
    smoke_only?: boolean;
}

export interface InstallWorkspaceRequest {
    activate_runtime?: boolean;
    auto_approve?: boolean;
}

export interface PreviewRenderRequest {
    theme_id?: string | null;
    width?: number | null;
    height?: number | null;
    surface_id?: string | null;
}

export interface StudioActionError {
    code: string;
    message: string;
    status: number;
    refusals: Array<Record<string, unknown>>;
    details: Record<string, unknown> | null;
}

export interface StudioOpenOptions {
    studioId?: string;
    template?: StudioTemplate;
    agentKind?: StudioAgentKind;
    initialPrompt?: string;
    initialName?: string;
}

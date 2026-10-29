
export type FolderMode = 'existing' | 'worktree';

export interface ExistingFolder {
    mode: 'existing';
    path: string;
}

export interface WorktreeFolder {
    mode: 'worktree';
    repo_path: string;
    base_branch: string;
    branch: string;
}

export type FolderSpec = ExistingFolder | WorktreeFolder;

export interface SessionSpec {
    label: string;
    family: string;
    model: string | null;
    folder: FolderSpec;
    skills: string[];
    opening_prompt: string | null;
    session_uuid?: string | null;
    theme?: string | null;
    keep_awake?: boolean | null;
    notifications_muted?: boolean | null;
    background?: { theme_id: string | null; dim: number | null; disabled: boolean } | null;
}

export interface BlueprintSpec {
    version: 1;
    name: string;
    shape_template: unknown;
    sessions: SessionSpec[];
}

export interface Blueprint {
    blueprint_uuid: string;
    name: string;
    spec: BlueprintSpec;
    created_at: string;
    updated_at: string;
}

export interface BlueprintList {
    status: 'ok' | 'unavailable' | string;
    blueprints: Blueprint[];
    detail: string | null;
}

export interface BlueprintError {
    code: string;
    detail: string;
    status: number;
    detectors: string[];
}

export interface WorktreeSettings {
    worktree_root: string;
}

export interface Problem {
    step: string;
    code: string;
    detail: string;
}

export interface WorktreeView {
    repo_path: string;
    base_branch: string;
    branch: string;
    path: string;
    create: boolean;
    branch_exists: boolean;
}

export interface FolderView {
    mode: FolderMode;
    path: string | null;
    worktree: WorktreeView | null;
}

export interface ProjectView {
    known: boolean;
    name: string | null;
}

export interface SkillView {
    item_id: string;
    state: string;
    version: string | null;
    needs_consent: boolean;
    instructions_write?: boolean;
    instructions_details?: string[];
    instructions_more?: number;
    consent_sheet: Record<string, unknown> | null;
    code: string | null;
    detail: string | null;
    refusal: Record<string, unknown> | null;
}

export interface MemberPreview {
    index: number;
    label: string;
    family: string;
    family_name: string | null;
    folder: FolderView;
    project: ProjectView | null;
    skills: SkillView[];
    skill_roots_to_create: string[];
    opening_prompt: boolean;
    problems: Problem[];
}

export interface LaunchPreviewResponse {
    blueprint_uuid: string;
    name: string;
    worktree_root: string;
    members: MemberPreview[];
}

export interface LaunchedSession {
    id: string;
    tmux_session: string | null;
    session_row_id: number | null;
    session_uuid: string | null;
}

export interface MemberOutcome {
    index: number;
    label: string;
    state: 'launched' | 'reused' | 'woken' | 'failed';
    folder: FolderView;
    project: ProjectView | null;
    skills: SkillView[];
    session: LaunchedSession | null;
    problem: Problem | null;
}

export interface LaunchResponse {
    blueprint_uuid: string;
    name: string;
    complete: boolean;
    members: MemberOutcome[];
    layout: { layout_uuid?: string; name?: string } | null;
    layout_detail: string | null;
    layout_updated?: boolean;
}

export interface SkillConsent {
    digest: string;
    body_sha: string;
    scripts: true;
}

export function blankSession(label: string): SessionSpec {
    return {
        label,
        family: 'claude',
        model: null,
        folder: { mode: 'existing', path: '' },
        skills: [],
        opening_prompt: null,
    };
}

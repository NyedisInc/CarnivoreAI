
export type ClaudeState = 'on' | 'name-only' | 'user-invocable-only' | 'off';

export type CodexState = 'on' | 'off';

export interface ToggleInfo {
    readonly kind: 'four_state' | 'on_off' | 'none';
    readonly states: readonly string[];
    readonly reason: string | null;
}

export interface ManagedInfo {
    readonly source: 'ledger' | 'sidecar';
    readonly item_id?: string;
    readonly version?: string;
    readonly scope?: string;
    readonly update_available?: boolean;
}

export interface SkillLocationRow {
    readonly location_id: string;
    readonly root_key: string;
    readonly folder: string;
    readonly name: string;
    readonly harness: 'claude' | 'codex';
    readonly scope: 'personal' | 'project' | 'plugin' | 'system';
    readonly path: string;
    readonly description: string;
    readonly card_art?: { readonly id: string; readonly rev: string | null } | null;
    readonly card_summary?: string | null;
    readonly card_lead?: string | null;
    readonly description_tokens_est: number;
    readonly is_symlink: boolean;
    readonly link_target: string | null;
    readonly read_only: boolean;
    readonly plugin: string | null;
    readonly project_path: string | null;
    readonly toggle: ToggleInfo;
    readonly state: string;
    readonly state_source: string | null;
    readonly managed: ManagedInfo | null;
    readonly shadowed_by: string | null;
    readonly shadows: readonly string[];
    readonly extends?: string | null;
    readonly guide_rev?: number | null;
    readonly behind_rules?: BehindRules | null;
}

export interface BehindRules {
    readonly written_for: number;
    readonly current: number;
    readonly changes: readonly { readonly rev: number; readonly summary: string }[];
}

export interface SkillGroupRow {
    readonly name: string;
    readonly locations: readonly SkillLocationRow[];
}

export interface ProfileGroupRow {
    readonly group_id: string;
    readonly profiles: readonly string[];
    readonly own_folder: boolean;
    readonly exists: boolean;
}

export interface Inventory {
    readonly context: { readonly profile: string; readonly group_id: string; readonly project_path: string | null };
    readonly profile_groups: readonly ProfileGroupRow[];
    readonly skills: readonly SkillGroupRow[];
    readonly settings_unparseable: readonly string[];
    readonly tokens_label: string;
}

export interface OverrideResult {
    readonly harness: string;
    readonly file: string;
    readonly skill: string;
    readonly state: string | null;
    readonly wrote: boolean;
    readonly restart_required: boolean;
    readonly reload_hint: string | null;
}

export type OverrideFile = 'user' | 'project' | 'local';

export interface SessionSkill {
    readonly name: string;
    readonly location_id: string;
    readonly scope: 'personal' | 'project' | 'plugin' | 'system';
    readonly state: string;
    readonly state_source: string | null;
    readonly model_sees: boolean;
    readonly reason: string | null;
    readonly description_tokens_est: number;
    readonly tokens_est: number;
    readonly shadowed_by: string | null;
}

export interface SessionSkills {
    readonly state: 'ok' | 'unsupported';
    readonly family: string;
    readonly detail?: string;
    readonly profile?: { readonly source: string; readonly directory: string };
    readonly working_dir?: string;
    readonly skills?: readonly SessionSkill[];
    readonly budget_tokens_est?: number;
    readonly tokens_label?: string;
    readonly restart_required?: boolean;
    readonly reload_hint?: string | null;
}

export interface CensusFires {
    readonly d7: number;
    readonly d30: number;
    readonly d90: number;
}

export interface CensusRow {
    readonly name: string;
    readonly harnesses: readonly ('claude' | 'codex')[];
    readonly scopes: readonly string[];
    readonly locations: number;
    readonly states: Readonly<Record<string, string>>;
    readonly tokens_est: number;
    readonly fires: CensusFires | null;
}

export interface Census {
    readonly state: 'measured' | 'not_measured';
    readonly tokens_label: string;
    readonly skills: readonly CensusRow[];
}

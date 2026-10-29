export type { PublishTab } from '../catalog/menu/route';
export type { PublishAccount, PublishableSkill, PublishPreview, SubmissionReport } from '../catalog/publish';

export interface SubEvent {
    at: string;
    what: string;
    reason?: string;
    text?: string;
    version?: string;
}

export interface SubRow {
    id: string;
    status: string;
    gate_state: string;
    item_id: string;
    kind: string;
    name: string;
    version: string;
    new_version: boolean;
    media_only: boolean;
    reason: string;
    appeals_left: number | null;
    created_at: string;
    decided_at: string;
    published_at: string;
    revoked_at: string;
    revocation_reason: string;
    events: SubEvent[];
}

export interface Limits {
    per_day: number | null;
    used_today: number | null;
    new_account: boolean;
    new_account_per_day: number | null;
    new_account_days: number | null;
    open_max: number | null;
    open_now: number | null;
    cooldown_until: string;
    strikes: number | null;
    strikes_max: number | null;
    appeals_max: number | null;
    media_per_day: number | null;
    media_used_today: number | null;
}

export interface RuleKind {
    kind: string;
    open: boolean;
}

export interface Rules {
    kinds: RuleKind[];
    caps: Record<string, number>;
}

export interface LocalCheck {
    version: string;
    ok: boolean;
    at: string;
    summary: string;
    grade?: string;
    files?: number | null;
    bytes?: number | null;
    digest?: string;
    findings?: { code: string; path: string }[];
}

export interface LocalSend {
    submission_id: string;
    version: string;
    sent_at: string;
    hero: string;
    media_submission_id?: string;
    hero_sha?: string;
}

export interface Facts {
    location: string;
    declared_version: string;
    changed_files: number;
    changed_at: string;
    made_at: string;
    sends: LocalSend[];
    checks: LocalCheck[];
}

export type Source = 'account' | 'mine' | 'folders' | 'limits' | 'rules' | 'facts' | 'report';

export type ActionName = 'check' | 'send' | 'media' | 'appeal' | 'withdraw' | 'register';

export interface CheckEntry {
    version: string;
    ok: boolean;
    at: string;
    summary: string;
    preview: import('../catalog/publish').PublishPreview | null;
    findings?: { code: string; path: string }[];
}

export type WizardPage = 0 | 1 | 2 | 3;

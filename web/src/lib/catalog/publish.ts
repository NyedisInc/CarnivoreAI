import { hostWindow } from '../sessions/env';
import { publishRefusalKey } from '../../../../client/js/labels/skill-publish.js';
import { reasonOf } from '../../../../client/js/labels/skill.js';
import { clipChars } from './bounds';
import type { CatalogAuthSession } from './types';

export interface PublishableSkill {
    location: string;
    kind?: string;
    name: string;
    harness: string;
    description: string;
    is_symlink?: boolean;
}

export interface LintBlock {
    grade?: string;
    checked?: number;
    failed?: { rule?: string; level?: string; detail?: string }[];
    not_graded?: string[];
}

export interface PublishPreview {
    location: string;
    kind?: string;
    name: string;
    version: string;
    file_count: number;
    total_bytes: number;
    files: { path: string; size: number | null }[];
    refusals: { code: string; detail?: string | null; path?: string | null }[];
    lint: LintBlock;
    cost: { description_tokens_est?: number };
    compat: { harness?: string; compatibility?: string | null };
    digest: string;
    can_send: boolean;
}

export interface MySubmission {
    submission_id: string;
    status: string;
    item_id: string;
    kind?: string;
    name?: string;
    version: string;
    new_version?: boolean;
    media_only?: boolean;
    reason?: string;
    gate_state?: string;
}

export interface ReportFinding {
    code: string;
    path?: string;
    line?: number;
}

export interface ReportGate {
    id: string;
    verdict: string;
    code: string;
    fix: string;
    findings: ReportFinding[];
}

export interface SubmissionReport {
    outcome: string;
    gates: ReportGate[];
}

export interface PublishAccount {
    provider: string | null;
    login: string | null;
    handle: string;
    handle_status: string;
    can_claim: boolean;
    registered: boolean;
    terms_version: string;
    terms_url: string;
    terms_accepted?: string;
}

export interface PublishHost {
    catalogSession(): Promise<CatalogAuthSession>;
    listSkills(): Promise<{ skills: PublishableSkill[] }>;
    preview(body: { location: string; version: string }): Promise<PublishPreview>;
    send(body: { location: string; version: string; digest: string }): Promise<{
        submission_id?: string;
        item_id?: string;
        status?: string;
    }>;
    mySubmissions(): Promise<{ submissions: MySubmission[] }>;
    submissionReport(submissionId: string): Promise<SubmissionReport>;
    sendHero(body: { kind: string; name: string; image_base64: string; source?: 'made' | 'yours' }): Promise<{ submission_id?: string }>;
    account(): Promise<PublishAccount>;
    register(body: {
        terms_version?: string;
        age_16_plus?: boolean;
        handle?: string;
    }): Promise<{ handle: string; handle_status: string; registered: boolean }>;
    changeHandle(handle: string): Promise<{ handle: string; held_until: number | null; next_rename_at: number | null }>;
}

interface LegacyApi {
    getCatalogSession: PublishHost['catalogSession'];
    getPublishableSkills: PublishHost['listSkills'];
    previewPublish: PublishHost['preview'];
    sendSubmission: PublishHost['send'];
    getMySubmissions: PublishHost['mySubmissions'];
    getSubmissionReport: PublishHost['submissionReport'];
    sendHeroImage: PublishHost['sendHero'];
    getPublishAccount: PublishHost['account'];
    registerCatalogAccount: PublishHost['register'];
    changeCatalogHandle: PublishHost['changeHandle'];
}

export function browserPublishHost(): PublishHost {
    const api = (): LegacyApi =>
        (hostWindow() as unknown as { API: LegacyApi } | undefined)?.API as LegacyApi;
    return {
        catalogSession: () => api().getCatalogSession(),
        listSkills: () => api().getPublishableSkills(),
        preview: (body) => api().previewPublish(body),
        send: (body) => api().sendSubmission(body),
        mySubmissions: () => api().getMySubmissions(),
        submissionReport: (id) => api().getSubmissionReport(id),
        sendHero: (body) => api().sendHeroImage(body),
        account: () => api().getPublishAccount(),
        register: (body) => api().registerCatalogAccount(body),
        changeHandle: (handle) => api().changeCatalogHandle(handle),
    };
}

export function fileToBase64(file: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ''));
        reader.onerror = () => reject(reader.error ?? new Error());
        reader.readAsDataURL(file);
    });
}

export const MAX_DETAIL_CHARS = 300;

export function errorText(
    error: unknown,
    t: (key: string, params?: Record<string, unknown> | null) => string,
): string {
    const detail = (error as { detail?: { code?: unknown; detail?: unknown } } | null)?.detail;
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
        return t(publishRefusalKey(detail.code), {
            code: detail.code,
            detail: clipChars(typeof detail.detail === 'string' ? detail.detail : '', MAX_DETAIL_CHARS) ?? '',
        });
    }
    return clipChars(reasonOf(error, t), MAX_DETAIL_CHARS) ?? '';
}

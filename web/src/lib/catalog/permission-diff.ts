import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
import { refusalPayloadOf } from './install-actions';

export const PERMISSION_DIFF_CATEGORIES = [
    'read',
    'write',
    'network',
    'secrets',
    'services_provides',
    'services_consumes',
    'events_on',
    'events_emit',
    'ui_slots',
    'harnesses',
    'channels',
] as const;

export type PermissionDiffCategory = (typeof PERMISSION_DIFF_CATEGORIES)[number];

export const PERMISSION_CATEGORY_LABEL_KEYS: Readonly<Record<PermissionDiffCategory, string>> = {
    read: SKILL_KEYS.permCatRead,
    write: SKILL_KEYS.permCatWrite,
    network: SKILL_KEYS.permCatNetwork,
    secrets: SKILL_KEYS.permCatSecrets,
    services_provides: SKILL_KEYS.permCatServicesProvides,
    services_consumes: SKILL_KEYS.permCatServicesConsumes,
    events_on: SKILL_KEYS.permCatEventsOn,
    events_emit: SKILL_KEYS.permCatEventsEmit,
    ui_slots: SKILL_KEYS.permCatUiSlots,
    harnesses: SKILL_KEYS.permCatHarnesses,
    channels: SKILL_KEYS.permCatChannels,
};

export interface PermissionDiffCategoryEntry {
    readonly category: PermissionDiffCategory;
    readonly added: readonly string[];
    readonly removed: readonly string[];
}

export interface ExecutionEscalationData {
    readonly tier0ToRun: boolean;
    readonly runModeChanged: boolean;
    readonly runCmdChanged: boolean;
    readonly trustEscalated: boolean;
    readonly hasAny: boolean;
}

export interface ProvenanceDiffData {
    readonly commitShaMismatch: boolean;
    readonly repoChanged: boolean;
    readonly oldRepo: string | null;
    readonly newRepo: string | null;
    readonly oldTag: string | null;
    readonly newTag: string | null;
    readonly oldCommitSha: string | null;
    readonly newCommitSha: string | null;
    readonly hasChange: boolean;
}

export interface PermissionDiffData {
    readonly requiresReconsent: boolean;
    readonly categories: readonly PermissionDiffCategoryEntry[];
    readonly executionEscalation: ExecutionEscalationData;
    readonly provenance: ProvenanceDiffData;
}

export interface StructuredReviewWarning {
    readonly kind: string;
    readonly detail: string;
    readonly file: string | null;
}

export interface FlaggedWarningMeta {
    readonly flagged: boolean;
    readonly requiresWarningAck: boolean;
    readonly summary: string | null;
    readonly warningReasons: readonly string[];
    readonly warnings: readonly StructuredReviewWarning[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
}

function stringList(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return value
        .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        .map((item) => item.trim());
}

function cleanStr(value: unknown): string | null {
    return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

export function parsePermissionDiff(raw: unknown): PermissionDiffData | null {
    const obj = asRecord(raw);
    if (!obj) return null;

    const addedBlock = asRecord(obj.added);
    const removedBlock = asRecord(obj.removed);
    const categories: PermissionDiffCategoryEntry[] = [];

    for (const category of PERMISSION_DIFF_CATEGORIES) {
        const directCat = asRecord(obj[category]);
        const added = [
            ...stringList(addedBlock?.[category]),
            ...stringList(directCat?.added),
        ];
        const removed = [
            ...stringList(removedBlock?.[category]),
            ...stringList(directCat?.removed),
        ];
        if (added.length > 0 || removed.length > 0) {
            categories.push({ category, added, removed });
        }
    }

    const escObj = asRecord(obj.execution_escalation);
    const tier0ToRun = escObj?.tier0_to_run === true;
    const runModeChanged = escObj?.run_mode_changed === true;
    const runCmdChanged = escObj?.run_cmd_changed === true;
    const trustEscalated = escObj?.trust_escalated === true;
    const executionEscalation: ExecutionEscalationData = {
        tier0ToRun,
        runModeChanged,
        runCmdChanged,
        trustEscalated,
        hasAny: tier0ToRun || runModeChanged || runCmdChanged || trustEscalated,
    };

    const provObj = asRecord(obj.provenance);
    const commitShaMismatch = provObj?.commit_sha_mismatch === true;
    const repoChanged = provObj?.repo_changed === true;
    const oldRepo = cleanStr(provObj?.old_repo);
    const newRepo = cleanStr(provObj?.new_repo);
    const oldTag = cleanStr(provObj?.old_tag);
    const newTag = cleanStr(provObj?.new_tag);
    const oldCommitSha = cleanStr(provObj?.old_commit_sha);
    const newCommitSha = cleanStr(provObj?.new_commit_sha);
    const hasTagChange = Boolean(oldTag && newTag && oldTag !== newTag);
    const provenance: ProvenanceDiffData = {
        commitShaMismatch,
        repoChanged,
        oldRepo,
        newRepo,
        oldTag,
        newTag,
        oldCommitSha,
        newCommitSha,
        hasChange: commitShaMismatch || repoChanged || hasTagChange,
    };

    const requiresReconsent =
        obj.requires_reconsent === true ||
        categories.some((c) => c.added.length > 0) ||
        executionEscalation.hasAny;

    return {
        requiresReconsent,
        categories,
        executionEscalation,
        provenance,
    };
}

export function permissionDiffFromError(error: unknown): PermissionDiffData | null {
    const payload = refusalPayloadOf(error);
    const directObj = asRecord(error);
    const bodyObj = asRecord(directObj?.body);
    const detailObj = asRecord(directObj?.detail) ?? asRecord(bodyObj?.detail);
    const candidates = [
        payload?.permission_diff,
        asRecord(payload?.diff)?.permission_diff,
        directObj?.permission_diff,
        bodyObj?.permission_diff,
        detailObj?.permission_diff,
        asRecord(detailObj?.diff)?.permission_diff,
    ];
    for (const candidate of candidates) {
        const parsed = parsePermissionDiff(candidate);
        if (parsed) return parsed;
    }
    return null;
}

export function hasPermissionDiffChanges(diff: PermissionDiffData | null | undefined): boolean {
    if (!diff) return false;
    return (
        diff.categories.length > 0 ||
        diff.executionEscalation.hasAny ||
        diff.provenance.hasChange ||
        diff.requiresReconsent
    );
}

export function isProvenanceBlocked(diff: PermissionDiffData | null | undefined): boolean {
    return Boolean(diff?.provenance.commitShaMismatch);
}

export function hasExecutionEscalation(diff: PermissionDiffData | null | undefined): boolean {
    return Boolean(diff?.executionEscalation.hasAny);
}

function structuredWarnings(value: unknown): StructuredReviewWarning[] {
    if (!Array.isArray(value)) return [];
    const out: StructuredReviewWarning[] = [];
    for (const entry of value) {
        const rec = asRecord(entry);
        if (!rec) continue;
        const kind = cleanStr(rec.kind);
        if (!kind) continue;
        out.push({
            kind,
            detail: cleanStr(rec.detail) ?? '',
            file: cleanStr(rec.file),
        });
    }
    return out;
}

export function flaggedMetaFromSheet(
    raw: unknown,
    fallback?: { readonly flagged?: boolean; readonly reviewSummary?: string | null } | null,
): FlaggedWarningMeta {
    const obj = asRecord(raw);
    const review = asRecord(obj?.review);
    const verdict = cleanStr(review?.verdict)?.toLowerCase() ?? cleanStr(obj?.review_verdict)?.toLowerCase();
    const explicitFlagged = obj?.flagged === true || verdict === 'flagged';
    const requiresAck = obj?.requires_warning_ack === true || explicitFlagged || fallback?.flagged === true;
    const flagged = explicitFlagged || requiresAck;
    const summary =
        cleanStr(review?.summary) ?? cleanStr(obj?.review_summary) ?? cleanStr(fallback?.reviewSummary);
    const warningReasons = stringList(obj?.warning_reasons);
    const warnings = structuredWarnings(review?.warnings);

    return {
        flagged,
        requiresWarningAck: requiresAck,
        summary,
        warningReasons,
        warnings,
    };
}

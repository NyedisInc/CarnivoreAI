import type { SubmissionRow } from './admin.js';
import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

export interface SubmissionProvenanceM5 {
    repo?: string;
    tag?: string;
    commit_sha?: string;
}

export interface SubmissionRowM5 extends SubmissionRow {
    review_verdict?: string;
    flagged?: boolean;
    requires_warning_ack?: boolean;
    warning_reasons?: string[];
    review_summary?: string;
    git_repo?: string;
    git_tag?: string;
    git_commit_sha?: string;
    provenance?: SubmissionProvenanceM5;
}

export type AdminBadgeTone = 'good' | 'warn' | 'bad';

export interface ReviewVerdictPill {
    key: string;
    tone: AdminBadgeTone;
    flagged: boolean;
}

const REVOCABLE_STATUSES = new Set(['published', 'approved', 'publishing']);

export function canRevokeStatus(status: string | undefined | null): boolean {
    return typeof status === 'string' && REVOCABLE_STATUSES.has(status);
}

export function asSubmissionM5(row: SubmissionRow): SubmissionRowM5 {
    return row as SubmissionRowM5;
}

export function reviewVerdictBadge(row: SubmissionRowM5): ReviewVerdictPill | null {
    const verdict = typeof row.review_verdict === 'string' ? row.review_verdict.trim().toLowerCase() : '';
    const flagged = row.flagged === true || row.requires_warning_ack === true || verdict === 'flagged';
    if (verdict === 'blocked') {
        return { key: ADMIN_KEYS.queueBadgeBlocked, tone: 'bad', flagged };
    }
    if (flagged) {
        return { key: ADMIN_KEYS.queueBadgeFlagged, tone: 'warn', flagged: true };
    }
    if (verdict === 'clean') {
        return { key: ADMIN_KEYS.queueBadgeClean, tone: 'good', flagged: false };
    }
    return null;
}

export function warningReasonsOf(row: SubmissionRowM5): string[] {
    if (!Array.isArray(row.warning_reasons)) return [];
    return row.warning_reasons.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

export function gitSourceLabel(row: SubmissionRowM5): { source: string; commit: string } {
    const repo = (row.git_repo || row.provenance?.repo || '').trim();
    const tag = (row.git_tag || row.provenance?.tag || '').trim();
    const commit = (row.git_commit_sha || row.provenance?.commit_sha || '').trim();
    const source = repo && tag ? `${repo}@${tag}` : repo || tag;
    return { source, commit };
}

import { REVIEW_BLOCKING_KINDS, REVIEW_INSTRUCTIONS_WRITE_KIND, REVIEW_KINDS } from '../../../../client/js/labels/skill.js';
import type { CatalogReview, CatalogReviewWarning } from './types';

export const MAX_WARNINGS = 50;

export const MAX_DETAIL_CHARS = 500;
export const MAX_INSTRUCTIONS_DETAILS = 3;
export const MAX_INSTRUCTIONS_DETAIL_CHARS = 200;

export const MAX_KIND_CHARS = 64;

export const MAX_SUMMARY_CHARS = 1000;

export const MAX_FILE_CHARS = 300;

export const MAX_REASON_CHARS = 500;

export const MAX_BY_CHARS = 100;

const STATED_VERDICTS = new Set(['clean', 'flagged', 'blocked']);

const CLIP_MARK = '...';

/* could not */
export type ReviewShape = 'absent' | 'unavailable' | 'reviewed';

export type ReviewVerdict = 'clean' | 'flagged' | 'blocked' | 'unreadable';

export interface WarningView {
    kind: string | null;
    detail: string | null;
    file: string | null;
    line: number | null;
}

export interface ReviewView {
    shape: ReviewShape;
    summary: string | null;
    warnings: WarningView[];
    malformed: boolean;
    /* could not */
    verdict: ReviewVerdict | null;
    writesInstructions: boolean;
    instructionsDetails: string[];
    instructionsMore: number;
    overridden: boolean;
    overrideReason: string | null;
    overrideBy: string | null;
    overrideAt: string | null;
}

function permittedVerdicts(found: FindingSummary, malformed: boolean): Set<string> {
    if (malformed) return new Set();
    if (!found.count) return new Set(['clean']);
    if (found.blocking) return new Set(['blocked']);
    return found.unknown ? new Set(['flagged', 'blocked']) : new Set(['flagged']);
}

interface FindingSummary {
    count: number;
    blocking: boolean;
    unknown: boolean;
    instructionsWrite: boolean;
}

function lineOf(value: unknown): number | null {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) return null;
    return value;
}

function clip(value: string | null, limit: number): string | null {
    if (value === null) return null;
    const points = Array.from(value);
    if (points.length <= limit) return value;
    return points.slice(0, limit - CLIP_MARK.length).join('') + CLIP_MARK;
}

function shown(value: unknown, limit: number): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? clip(trimmed, limit) : null;
}

function overrideDate(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const match = /^(\d{4}-\d{2}-\d{2})T/.exec(value.trim());
    return match?.[1] ?? null;
}

export function reviewView(review: CatalogReview | null | undefined): ReviewView {
    if (!review || typeof review !== 'object') {
        return {
            shape: 'absent',
            summary: null,
            warnings: [],
            malformed: false,
            verdict: null,
            writesInstructions: false,
            instructionsDetails: [],
            instructionsMore: 0,
            overridden: false,
            overrideReason: null,
            overrideBy: null,
            overrideAt: null,
        };
    }
    const status = review.status;
    const shape: ReviewShape = status === 'reviewed' ? 'reviewed' : 'unavailable';
    const raw = review.warnings;
    const stated = raw !== undefined && raw !== null;
    const malformed = stated && !Array.isArray(raw);
    const warnings: WarningView[] = [];
    const found: FindingSummary = { count: 0, blocking: false, unknown: false, instructionsWrite: false };
    const instructionsDetails: string[] = [];
    let instructionsFindings = 0;
    if (Array.isArray(raw)) {
        for (const entry of raw) {
            const warning = (entry || {}) as CatalogReviewWarning;
            const kind = shown(warning.kind, MAX_KIND_CHARS);
            found.count += 1;
            if (REVIEW_BLOCKING_KINDS.has(kind ?? '')) found.blocking = true;
            else if (!REVIEW_KINDS.has(kind ?? '')) found.unknown = true;
            if (kind === REVIEW_INSTRUCTIONS_WRITE_KIND) {
                found.instructionsWrite = true;
                instructionsFindings += 1;
                const detail = shown(warning.detail, MAX_INSTRUCTIONS_DETAIL_CHARS);
                if (detail !== null && instructionsDetails.length < MAX_INSTRUCTIONS_DETAILS) {
                    instructionsDetails.push(detail);
                }
            }
            if (warnings.length >= MAX_WARNINGS) continue;
            warnings.push({
                kind,
                detail: shown(warning.detail, MAX_DETAIL_CHARS),
                file: shown(warning.file, MAX_FILE_CHARS),
                line: lineOf(warning.line),
            });
        }
    }
    let verdict: ReviewVerdict | null = null;
    if (shape === 'reviewed') {
        const claimed = review.verdict;
        if (claimed !== undefined && claimed !== null) {
            const token = typeof claimed === 'string' ? claimed.trim() : '';
            const permitted = permittedVerdicts(found, malformed);
            verdict = STATED_VERDICTS.has(token) && permitted.has(token)
                ? (token as ReviewVerdict)
                : 'unreadable';
        }
    }
    const claimedOverride = review.override;
    const overrideBlock = shape === 'reviewed'
            && claimedOverride
            && typeof claimedOverride === 'object'
            && !Array.isArray(claimedOverride)
        ? (claimedOverride as { reason?: unknown; by?: unknown; at?: unknown })
        : null;
    const overrideReason = overrideBlock ? shown(overrideBlock.reason, MAX_REASON_CHARS) : null;
    const overrideBy = overrideReason !== null ? shown(overrideBlock?.by, MAX_BY_CHARS) : null;
    const overrideAt = overrideReason !== null ? overrideDate(overrideBlock?.at) : null;
    return {
        shape,
        summary: shown(review.summary, MAX_SUMMARY_CHARS),
        warnings: shape === 'reviewed' ? warnings : [],
        malformed: shape === 'reviewed' ? malformed : false,
        verdict,
        writesInstructions: shape === 'reviewed' ? found.instructionsWrite : false,
        instructionsDetails: shape === 'reviewed' ? instructionsDetails : [],
        instructionsMore: shape === 'reviewed' ? instructionsFindings - instructionsDetails.length : 0,
        overridden: overrideReason !== null,
        overrideReason,
        overrideBy,
        overrideAt,
    };
}

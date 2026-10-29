import { clipChars } from './bounds';
import type { CatalogGrade, CatalogGradeFailure } from './types';

export const UNGRADED = 'ungraded';

export const MAX_RULE_CHARS = 64;

export const MAX_DETAIL_CHARS = 240;

export const MAX_FAILURES = 50;

export const MAX_NOT_GRADED = 50;

export type GradeShape = 'absent' | 'ungraded' | 'graded';

export interface GradeFailureView {
    rule: string | null;
    level: string | null;
    detail: string | null;
}

export interface GradeView {
    shape: GradeShape;
    letter: string | null;
    checked: number | null;
    failed: GradeFailureView[];
    notGraded: string[];
    failedMalformed: boolean;
}

const ABSENT: GradeView = {
    shape: 'absent',
    letter: null,
    checked: null,
    failed: [],
    notGraded: [],
    failedMalformed: false,
};

function countOf(value: unknown): number | null {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    if (value < 0) return null;
    return Math.trunc(value);
}

function shown(value: unknown, limit: number): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? clipChars(trimmed, limit) : null;
}

function notGradedOf(raw: unknown): string[] {
    if (!Array.isArray(raw)) return [];
    const ids: string[] = [];
    for (const entry of raw) {
        if (ids.length >= MAX_NOT_GRADED) break;
        const id = shown(entry, MAX_RULE_CHARS);
        if (id) ids.push(id);
    }
    return ids;
}

export function gradeView(grade: CatalogGrade | null | undefined): GradeView {
    if (!grade || typeof grade !== 'object') return ABSENT;

    const letter = shown(grade.grade, MAX_RULE_CHARS);
    if (letter === null) return ABSENT;

    const checked = countOf(grade.checked);
    const notGraded = notGradedOf(grade.not_graded);

    if (letter === UNGRADED) {
        // there is nothing
        return {
            shape: 'ungraded',
            letter: null,
            checked,
            failed: [],
            notGraded,
            failedMalformed: false,
        };
    }

    const raw = grade.failed;
    const stated = raw !== undefined && raw !== null;
    const failedMalformed = stated && !Array.isArray(raw);
    const failed: GradeFailureView[] = [];
    if (Array.isArray(raw)) {
        for (const entry of raw) {
            if (failed.length >= MAX_FAILURES) break;
            const failure = (entry || {}) as CatalogGradeFailure;
            failed.push({
                rule: shown(failure.rule, MAX_RULE_CHARS),
                level: shown(failure.level, MAX_RULE_CHARS),
                detail: shown(failure.detail, MAX_DETAIL_CHARS),
            });
        }
    }
    return { shape: 'graded', letter, checked, failed, notGraded, failedMalformed };
}

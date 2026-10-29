import { describe, expect, test } from 'vitest';

import {
    MAX_DETAIL_CHARS,
    MAX_FAILURES,
    MAX_RULE_CHARS,
    gradeView,
} from './grade';

const GRADED = {
    grade: 'B',
    checked: 12,
    failed: [
        { rule: 'description.trigger', level: 'recommended', detail: 'no trigger found' },
    ],
    not_graded: ['compatibility.length', 'metadata.shape'],
};

describe('which of the three shapes a grade is', () => {
    test('nothing carried at all is `absent`, and it is not a letter', () => {
        expect(gradeView(null).shape).toBe('absent');
        expect(gradeView(undefined).shape).toBe('absent');
        expect(gradeView(null).letter).toBeNull();
    });

    test('an `ungraded` letter is its OWN shape and is never an F', () => {
        const view = gradeView({ grade: 'ungraded', checked: 0, failed: [], not_graded: [] });
        expect(view.shape).toBe('ungraded');
    });

    test('a measured letter is `graded` and is carried verbatim', () => {
        const view = gradeView(GRADED);
        expect(view.shape).toBe('graded');
        expect(view.letter).toBe('B');
        expect(view.checked).toBe(12);
    });

    test('NEGATIVE CONTROL: absent carries no count, and NEVER a zero', () => {
        expect(gradeView(null).checked).toBeNull();
    });

    test('a letter this build has never seen is still rendered, not dropped', () => {
        expect(gradeView({ ...GRADED, grade: 'A+' }).letter).toBe('A+');
        expect(gradeView({ ...GRADED, grade: 'A+' }).shape).toBe('graded');
    });

    test('a letter that is not a string at all is `absent`, never a guess', () => {
        expect(gradeView({ ...GRADED, grade: 7 } as never).shape).toBe('absent');
    });
});

describe('what the grade checked, and what it could not', () => {
    test('a count that is not a number is null rather than zero', () => {
        expect(gradeView({ ...GRADED, checked: 'lots' } as never).checked).toBeNull();
    });

    test('the rules that did not run are carried, because they are not passes', () => {
        expect(gradeView(GRADED).notGraded).toEqual([
            'compatibility.length', 'metadata.shape',
        ]);
    });

    test('an empty failure list is a MEASURED zero on a graded block', () => {
        const view = gradeView({ grade: 'A', checked: 12, failed: [], not_graded: [] });
        expect(view.failed).toEqual([]);
        expect(view.failedMalformed).toBe(false);
    });
});

describe('every failure reaches the reader, and every string is bounded', () => {
    test('a failure keeps its rule, its level and its words', () => {
        expect(gradeView(GRADED).failed).toEqual([
            { rule: 'description.trigger', level: 'recommended', detail: 'no trigger found' },
        ]);
    });

    test('a runaway detail is clipped and the cut is never silent', () => {
        const view = gradeView({
            ...GRADED,
            failed: [{ rule: 'r', level: 'required', detail: 'y'.repeat(5000) }],
        });
        const detail = view.failed[0]?.detail ?? '';
        expect(detail.length).toBeLessThanOrEqual(MAX_DETAIL_CHARS);
        expect(detail.endsWith('...')).toBe(true);
    });

    test('a runaway rule id is clipped too', () => {
        const view = gradeView({
            ...GRADED,
            failed: [{ rule: 'z'.repeat(400), level: 'required', detail: 'd' }],
        });
        expect((view.failed[0]?.rule ?? '').length).toBeLessThanOrEqual(MAX_RULE_CHARS);
    });

    test('a runaway failure list is capped', () => {
        const failed = Array.from({ length: MAX_FAILURES + 40 }, () => ({
            rule: 'r', level: 'required', detail: 'd',
        }));
        expect(gradeView({ ...GRADED, failed }).failed).toHaveLength(MAX_FAILURES);
    });

    test('a failures value that is not a list is REPORTED, never coerced to empty', () => {
        const view = gradeView({ ...GRADED, failed: 'lots' } as never);
        expect(view.failedMalformed).toBe(true);
        expect(view.failed).toEqual([]);
    });

    test('a failure with no level is carried anyway, level null', () => {
        const view = gradeView({
            ...GRADED, failed: [{ rule: 'r', detail: 'd' }],
        });
        expect(view.failed[0]?.level).toBeNull();
        expect(view.failed[0]?.rule).toBe('r');
    });
});

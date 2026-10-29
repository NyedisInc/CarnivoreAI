/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import GradeBlock from './GradeBlock.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogGrade } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const GRADED: CatalogGrade = {
    grade: 'B',
    checked: 12,
    failed: [
        {
            rule: 'description.trigger',
            level: 'recommended',
            detail: 'no stated trigger condition was found',
        },
    ],
    not_graded: ['compatibility.length', 'metadata.shape'],
};

let panel: Record<string, unknown> | null = null;

function paint(grade: CatalogGrade | null): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(GradeBlock, { target, props: { grade, t } as never }) as never;
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('the letter, and the two times there must not be one', () => {
    test('NEGATIVE CONTROL AND ITS PAIR: absent shows no letter, graded does', () => {
        paint(null);
        expect(document.querySelector('.cat-grade__letter')).toBeNull();
        expect(document.body.textContent).toContain(i18n.t('skill.grade.absent'));

        unmount(panel as never);
        panel = null;
        document.body.innerHTML = '';

        paint(GRADED);
        expect(document.querySelector('.cat-grade__letter')).not.toBeNull();
        expect(document.body.textContent).toContain(
            i18n.t('skill.grade.letter', { letter: 'B' }),
        );
    });

    test('`ungraded` says NO RULE RAN and paints no letter at all', () => {
        paint({ grade: 'ungraded', checked: 0, failed: [], not_graded: [] });
        expect(document.querySelector('.cat-grade__letter')).toBeNull();
        expect(document.body.textContent).toContain(i18n.t('skill.grade.ungraded'));
    });

    test('an ungraded version is NOT reported as having satisfied anything', () => {
        paint({ grade: 'ungraded', checked: 0, failed: [], not_graded: [] });
        expect(document.body.textContent).not.toContain(
            i18n.t('skill.grade.no_failures'),
        );
    });

    test('a letter this build has never seen is still painted', () => {
        paint({ ...GRADED, grade: 'A+' });
        expect(document.body.textContent).toContain(
            i18n.t('skill.grade.letter', { letter: 'A+' }),
        );
    });
});

describe('what the grade found', () => {
    test('a failure is on the page with its rule and its words', () => {
        paint(GRADED);
        expect(document.querySelectorAll('.cat-grade__failure')).toHaveLength(1);
        expect(document.body.textContent).toContain('description.trigger');
        expect(document.body.textContent).toContain(
            'no stated trigger condition was found',
        );
    });

    test('NEGATIVE CONTROL: a clean grade says so in the GRADER\'s voice', () => {
        paint({ grade: 'A', checked: 12, failed: [], not_graded: [] });
        expect(document.querySelectorAll('.cat-grade__failure')).toHaveLength(0);
        expect(document.body.textContent).toContain(i18n.t('skill.grade.no_failures'));
    });

    test('rules that did NOT run are reported, never counted as passes', () => {
        paint(GRADED);
        expect(document.body.textContent).toContain(
            i18n.t('skill.grade.not_graded', { count: 2 }),
        );
    });

    test('a failure list that could not be read is reported, not painted clean', () => {
        paint({ ...GRADED, failed: 'lots' } as never);
        expect(document.body.textContent).toContain(
            i18n.t('skill.grade.failed.malformed'),
        );
        expect(document.body.textContent).not.toContain(
            i18n.t('skill.grade.no_failures'),
        );
    });
});

describe('the block is never silent', () => {
    test('the advisory line is on screen whatever the shape', () => {
        for (const grade of [null, GRADED, { grade: 'ungraded' } as CatalogGrade]) {
            paint(grade);
            expect(document.body.textContent).toContain(i18n.t('skill.grade.advisory'));
            unmount(panel as never);
            panel = null;
            document.body.innerHTML = '';
        }
    });

    test('a detail from the index is rendered as TEXT and never as markup', () => {
        paint({
            ...GRADED,
            failed: [{ rule: 'r', level: 'required', detail: '<img src=x onerror=alert(1)>' }],
        });
        expect(document.querySelector('.cat-grade img')).toBeNull();
        expect(document.body.textContent).toContain('<img src=x onerror=alert(1)>');
    });
});

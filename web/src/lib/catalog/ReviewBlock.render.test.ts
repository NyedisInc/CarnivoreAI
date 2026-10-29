/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import ReviewBlock from './ReviewBlock.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogReview } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let block: Record<string, unknown> | null = null;

function paint(review: CatalogReview | null): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    block = mount(ReviewBlock, { target, props: { review, t } }) as never;
}

function text(): string {
    return document.body.textContent ?? '';
}

afterEach(() => {
    if (block) unmount(block as never);
    block = null;
    document.body.innerHTML = '';
});

describe('the verdict reaches the status line', () => {
    test('a clean verdict says so, in words', () => {
        paint({ status: 'reviewed', summary: 's', verdict: 'clean', warnings: [] } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.verdict.clean'));
    });

    test('a blocked verdict says so, in words', () => {
        paint({
            status: 'reviewed',
            summary: 's',
            verdict: 'blocked',
            warnings: [{ kind: 'credential_access', detail: 'reads ~/.aws', file: 'SKILL.md' }],
        } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.verdict.blocked'));
    });

    test('a verdict this build cannot read says THAT, and never clean', () => {
        paint({ status: 'reviewed', summary: 's', verdict: 'clen', warnings: [] } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.verdict.unreadable'));
        expect(text()).not.toContain(i18n.t('skill.review.verdict.clean'));
    });

    test('NO VERDICT AT ALL says it is unreviewed for security, not clean', () => {
        paint({ status: 'reviewed', summary: 'nothing damaging was found.', warnings: [] } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.verdict.absent'));
        expect(text()).not.toContain(i18n.t('skill.review.verdict.clean'));
    });

    test('an unavailable review shows no verdict of any kind', () => {
        paint({ status: 'unavailable' } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.unavailable.detail'));
        for (const key of [
            'skill.review.verdict.clean',
            'skill.review.verdict.flagged',
            'skill.review.verdict.blocked',
            'skill.review.verdict.unreadable',
        ]) {
            expect(text(), key).not.toContain(i18n.t(key));
        }
    });
});

describe('where the finding is', () => {
    test('a file and a line are printed beside the finding', () => {
        paint({
            status: 'reviewed',
            summary: 's',
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'calls out', file: 'scripts/run.sh', line: 12 }],
        } as CatalogReview);
        expect(text()).toContain('scripts/run.sh');
        expect(text()).toContain('12');
    });

    test('a file with no line is printed without one', () => {
        paint({
            status: 'reviewed',
            summary: 's',
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'calls out', file: 'SKILL.md' }],
        } as CatalogReview);
        expect(text()).toContain('SKILL.md');
        expect(text()).toContain('calls out');
    });

    test('NEGATIVE CONTROL: a finding with no file prints no location', () => {
        paint({
            status: 'reviewed',
            summary: 's',
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'calls out' }],
        } as CatalogReview);
        expect(document.querySelectorAll('.cat-review__where')).toHaveLength(0);
        expect(text()).toContain('calls out');
    });
});

describe('an overridden item paints no blocked verdict and no override note (Alex (example-owner), 2026-10-16)', () => {
    const blocked = {
        status: 'reviewed',
        summary: 's',
        verdict: 'blocked',
        warnings: [{ kind: 'credential_access', detail: 'reads ~/.aws', file: 'SKILL.md' }],
    };

    test('overridden + blocked: no verdict word, no override callout, warnings still listed', () => {
        paint({ ...blocked, override: { reason: 'internal test fixture', by: 'Example-owner', at: '2026-09-19T16:02:14Z' } } as CatalogReview);
        expect(text()).not.toContain(i18n.t('skill.review.verdict.blocked'));
        expect(text()).not.toContain(i18n.t('skill.review.verdict.clean'));
        expect(text()).not.toContain('internal test fixture');
        expect(text()).not.toContain('Example-owner');
        expect(document.querySelectorAll('.cat-review__override, .cat-review__override-by')).toHaveLength(0);
        expect(text()).toContain('reads ~/.aws');
    });

    test('NEGATIVE CONTROL: a blocked item with no override still says blocked', () => {
        paint(blocked as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.verdict.blocked'));
    });
});

describe('the footer no longer calls the whole review advisory', () => {
    test('it says some findings block and the rest are advisory', () => {
        paint({ status: 'reviewed', summary: 's', verdict: 'clean', warnings: [] } as CatalogReview);
        expect(text()).toContain(i18n.t('skill.review.advisory'));
        expect(i18n.t('skill.review.advisory')).toContain('block');
    });
});

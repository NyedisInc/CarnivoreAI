import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, test } from 'vitest';

import { cardView } from './card';
import { reviewView } from './review';

const ARTIFACTS: Record<string, Record<string, unknown>> = JSON.parse(
    readFileSync(
        fileURLToPath(
            new URL('../../../../tests/fixtures/catalog_review_artifacts.json', import.meta.url),
        ),
        'utf8',
    ),
);

function artifact(name: string): Record<string, unknown> {
    const doc = ARTIFACTS[name];
    if (!doc) throw new Error(`the artifacts file carries no ${name}`);
    return doc;
}

const rowFor = (review: unknown) =>
    cardView({ latest: '1.0.0', versions: [{ v: '1.0.0', review }] } as never, false);

describe('the clean document the live index serves', () => {
    const doc = artifact('live_skill_clean');

    test('reads clean, with a measured zero findings', () => {
        const view = reviewView(doc as never);
        expect(view.shape).toBe('reviewed');
        expect(view.verdict).toBe('clean');
        expect(view.warnings).toEqual([]);
        expect(view.malformed).toBe(false);
        expect(view.overridden).toBe(false);
    });

    test('NEGATIVE CONTROL: it puts no mark on the card', () => {
        expect(rowFor(doc).flagged).toBe(false);
    });
});

describe('the blocked document the live index serves', () => {
    const doc = artifact('live_skill_blocked');

    test('reads blocked, and the finding keeps the file and line it named', () => {
        const view = reviewView(doc as never);
        expect(view.verdict).toBe('blocked');
        expect(view.warnings).toHaveLength(1);
        expect(view.warnings[0]).toMatchObject({
            kind: 'prompt_injection',
            file: 'SKILL.md',
            line: 7,
        });
        expect(view.warnings[0]?.detail).toBeTruthy();
    });

    test('and the card is marked', () => {
        expect(rowFor(doc).flagged).toBe(true);
        expect(rowFor(doc).warnings).toBe(1);
    });
});

describe('the blocked document the gate emitted, and its override', () => {
    const plain = artifact('fixture_blocked');
    const excused = artifact('fixture_blocked_with_override');

    test('three credential findings hold the verdict at blocked', () => {
        const view = reviewView(plain as never);
        expect(view.verdict).toBe('blocked');
        expect(view.warnings).toHaveLength(3);
        expect(view.warnings.map((w) => w.kind)).toEqual([
            'credential_access',
            'credential_access',
            'credential_access',
        ]);
        expect(view.warnings.map((w) => w.line)).toEqual([6, 7, 8]);
        expect(view.overridden).toBe(false);
        expect(view.overrideReason).toBeNull();
    });

    test('AN OVERRIDE EXCUSES THE PUBLISH AND NEVER THE VERDICT', () => {
        const view = reviewView(excused as never);
        expect(view.verdict).toBe('blocked');
        expect(view.overridden).toBe(true);
        expect(view.overrideReason).toBe('corpus fixture, never published');
    });

    test('the fixture also names who allowed it and when', () => {
        const view = reviewView(excused as never);
        expect(view.overrideBy).toBe('acme');
        expect(view.overrideAt).toBe('2026-09-19');
    });

    test('the plain one marks the card; the overridden one paints no flag', () => {
        expect(rowFor(plain).flagged).toBe(true);
        expect(rowFor(excused).flagged).toBe(false);
    });
});

describe('the unavailable document the live index serves', () => {
    const doc = artifact('live_skill_unavailable');

    test('carries NO verdict, and null is not clean', () => {
        const view = reviewView(doc as never);
        expect(view.shape).toBe('unavailable');
        expect(view.verdict).toBeNull();
        expect(view.verdict).not.toBe('clean');
        expect(view.warnings).toEqual([]);
    });

    test('it is not marked either, because nothing was found to mark', () => {
        expect(rowFor(doc).flagged).toBe(false);
    });
});

describe('the whole file', () => {
    test('every document reads without throwing, and none reads clean by accident', () => {
        const expected: Record<string, string | null> = {
            fixture_blocked: 'blocked',
            fixture_blocked_with_override: 'blocked',
            live_skill_clean: 'clean',
            live_skill_blocked: 'blocked',
            live_skill_unavailable: null,
        };
        const seen = Object.fromEntries(
            Object.entries(ARTIFACTS).map(([name, doc]) => [name, reviewView(doc as never).verdict]),
        );
        expect(seen).toEqual(expected);
    });

    test('the digest key it carries is ignored, not choked on', () => {
        for (const doc of Object.values(ARTIFACTS)) {
            expect(typeof doc.digest).toBe('string');
        }
        expect(reviewView(artifact('live_skill_clean') as never).verdict).toBe('clean');
    });
});

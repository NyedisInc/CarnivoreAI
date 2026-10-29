import { describe, expect, test } from 'vitest';

import { reviewView } from './review';
import { cardView } from './card';
import type { CatalogReview } from './types';

function reviewed(extra: Record<string, unknown>): CatalogReview {
    return { status: 'reviewed', summary: 'a summary', ...extra } as CatalogReview;
}

function flaggedOnCard(review: unknown): boolean {
    return cardView(
        { id: 'a/b', latest: '1', versions: [{ v: '1', review }] } as never,
        false,
    ).flagged;
}

describe('a verdict this build can take at face value', () => {
    test('clean, with no findings, is clean', () => {
        const view = reviewView(reviewed({ verdict: 'clean', warnings: [] }));
        expect(view.verdict).toBe('clean');
        expect(flaggedOnCard(reviewed({ verdict: 'clean', warnings: [] }))).toBe(false);
    });

    test('flagged, over an advisory finding, is flagged', () => {
        const block = reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'fetches mdn', file: 'SKILL.md' }],
        });
        expect(reviewView(block).verdict).toBe('flagged');
        expect(flaggedOnCard(block)).toBe(true);
    });

    test('blocked, over a blocking finding, is blocked', () => {
        const block = reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'credential_access', detail: 'reads ~/.aws', file: 'SKILL.md' }],
        });
        expect(reviewView(block).verdict).toBe('blocked');
        expect(flaggedOnCard(block)).toBe(true);
    });

    test('all five blocking kinds permit blocked', () => {
        for (const kind of [
            'prompt_injection',
            'credential_access',
            'obfuscation',
            'opaque_payload',
            'settings_write',
        ]) {
            const block = reviewed({
                verdict: 'blocked',
                warnings: [{ kind, detail: 'd', file: 'SKILL.md' }],
            });
            expect(reviewView(block).verdict, kind).toBe('blocked');
        }
    });

    test('instructions_write alone is flagged, and blocked once settings_write joins it', () => {
        const only = reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'instructions_write', detail: 'd', file: 'SKILL.md' }],
        });
        const view = reviewView(only);
        expect(view.verdict).toBe('flagged');
        expect(view.writesInstructions).toBe(true);
        expect(flaggedOnCard(only)).toBe(true);
        for (const verdict of ['blocked', 'clean']) {
            const claim = reviewed({ verdict, warnings: [{ kind: 'instructions_write', detail: 'd', file: 'a' }] });
            expect(reviewView(claim).verdict, verdict).toBe('unreadable');
        }
        const both = reviewed({
            verdict: 'blocked',
            warnings: [
                { kind: 'instructions_write', detail: 'd', file: 'SKILL.md' },
                { kind: 'settings_write', detail: 'd', file: 'SKILL.md' },
            ],
        });
        expect(reviewView(both).verdict).toBe('blocked');
    });

    test('an advisory kind may NOT be called blocked', () => {
        for (const kind of ['network', 'shell_exec', 'file_delete', 'privilege', 'description_mismatch', 'other']) {
            const block = reviewed({
                verdict: 'blocked',
                warnings: [{ kind, detail: 'd', file: 'SKILL.md' }],
            });
            expect(reviewView(block).verdict, kind).toBe('unreadable');
        }
    });
});

describe('a verdict that is not one of the three', () => {
    test('a typo is unreadable, never clean', () => {
        expect(reviewView(reviewed({ verdict: 'clen', warnings: [] })).verdict).toBe('unreadable');
    });

    test('a number, a boolean, a list and an object are unreadable', () => {
        for (const bad of [42, true, ['clean'], { verdict: 'clean' }]) {
            const view = reviewView(reviewed({ verdict: bad, warnings: [] }));
            expect(view.verdict, JSON.stringify(bad)).toBe('unreadable');
        }
    });

    test('an empty string and whitespace are unreadable, not absent', () => {
        expect(reviewView(reviewed({ verdict: '', warnings: [] })).verdict).toBe('unreadable');
        expect(reviewView(reviewed({ verdict: '   ', warnings: [] })).verdict).toBe('unreadable');
    });

    test('an unreadable verdict MARKS THE CARD, because it is not clean', () => {
        expect(flaggedOnCard(reviewed({ verdict: 'clen', warnings: [] }))).toBe(true);
        expect(flaggedOnCard(reviewed({ verdict: 42, warnings: [] }))).toBe(true);
    });
});

describe('a verdict that disagrees with the review\'s own findings', () => {
    test('clean beside ANY finding is discarded', () => {
        const block = reviewed({
            verdict: 'clean',
            warnings: [{ kind: 'network', detail: 'calls out', file: 'SKILL.md' }],
        });
        expect(reviewView(block).verdict).toBe('unreadable');
        expect(flaggedOnCard(block)).toBe(true);
    });

    test('flagged beside a BLOCKING finding is discarded', () => {
        const block = reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'prompt_injection', detail: 'addresses the agent', file: 'SKILL.md' }],
        });
        expect(reviewView(block).verdict).toBe('unreadable');
    });

    test('blocked with NO findings at all is discarded', () => {
        expect(reviewView(reviewed({ verdict: 'blocked', warnings: [] })).verdict).toBe('unreadable');
    });

    test('flagged with no findings is discarded too', () => {
        expect(reviewView(reviewed({ verdict: 'flagged', warnings: [] })).verdict).toBe('unreadable');
    });
});

describe('a warning kind from a newer build', () => {
    test('permits flagged and permits blocked, and neither is a false alarm', () => {
        const asFlagged = reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'a_kind_from_the_future', detail: 'd', file: 'SKILL.md' }],
        });
        const asBlocked = reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'a_kind_from_the_future', detail: 'd', file: 'SKILL.md' }],
        });
        expect(reviewView(asFlagged).verdict).toBe('flagged');
        expect(reviewView(asBlocked).verdict).toBe('blocked');
    });

    test('but it NEVER permits clean', () => {
        const block = reviewed({
            verdict: 'clean',
            warnings: [{ kind: 'a_kind_from_the_future', detail: 'd', file: 'SKILL.md' }],
        });
        expect(reviewView(block).verdict).toBe('unreadable');
    });

    test('the warning itself is still carried, as it always was', () => {
        const view = reviewView(reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'a_kind_from_the_future', detail: 'd', file: 'SKILL.md' }],
        }));
        expect(view.warnings).toHaveLength(1);
        expect(view.warnings[0]?.kind).toBe('a_kind_from_the_future');
    });
});

describe('the two silences, and neither of them is clean', () => {
    test('NO VERDICT AT ALL is null, the shape of everything published before verdicts', () => {
        const live: CatalogReview = {
            status: 'reviewed',
            summary: 'nothing damaging was found.',
            warnings: [],
        } as CatalogReview;
        expect(reviewView(live).verdict).toBe(null);
        expect(flaggedOnCard(live)).toBe(false);
    });

    test('an explicit null verdict reads as no verdict, never as clean', () => {
        const view = reviewView(reviewed({ verdict: null, warnings: [] }));
        expect(view.verdict).toBe(null);
    });

    test('an UNAVAILABLE review has no verdict, whatever it claims', () => {
        const view = reviewView({ status: 'unavailable', verdict: 'clean' } as CatalogReview);
        expect(view.shape).toBe('unavailable');
        expect(view.verdict).toBe(null);
        expect(view.overridden).toBe(false);
    });

    test('an ABSENT review block has no verdict', () => {
        expect(reviewView(null).verdict).toBe(null);
        expect(reviewView(undefined).verdict).toBe(null);
    });
});

describe('where a finding is', () => {
    test('a file and a line are carried', () => {
        const view = reviewView(reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'd', file: 'scripts/run.sh', line: 12 }],
        }));
        expect(view.warnings[0]?.file).toBe('scripts/run.sh');
        expect(view.warnings[0]?.line).toBe(12);
    });

    test('a missing line never discards the finding', () => {
        const view = reviewView(reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'd', file: 'SKILL.md' }],
        }));
        expect(view.warnings).toHaveLength(1);
        expect(view.warnings[0]?.line).toBe(null);
    });

    test('a line that is not a whole positive number is dropped, the finding is not', () => {
        for (const bad of ['12', 0, -4, 1.5, Number.NaN, Infinity, null, {}]) {
            const view = reviewView(reviewed({
                verdict: 'flagged',
                warnings: [{ kind: 'network', detail: 'd', file: 'SKILL.md', line: bad }],
            }));
            expect(view.warnings, JSON.stringify(bad)).toHaveLength(1);
            expect(view.warnings[0]?.line, JSON.stringify(bad)).toBe(null);
        }
    });

    test('a file is clipped like every other string the index wrote', () => {
        const view = reviewView(reviewed({
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'd', file: 'a'.repeat(5000) }],
        }));
        expect((view.warnings[0]?.file ?? '').length).toBeLessThan(500);
        expect(view.warnings[0]?.file?.endsWith('...')).toBe(true);
    });
});

describe('an override, which excuses a block and never erases it', () => {
    test('a well formed override is reported with its reason', () => {
        const block = reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
            override: { reason: 'internal fixture', by: 'acme', at: '2026-09-19T00:00:00Z' },
        });
        const view = reviewView(block);
        expect(view.overridden).toBe(true);
        expect(view.overrideReason).toBe('internal fixture');
        expect(view.overrideBy).toBe('acme');
        expect(view.overrideAt).toBe('2026-09-19');
    });

    test('reviewView keeps the verdict, but the card paints none', () => {
        const block = reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
            override: { reason: 'internal fixture' },
        });
        expect(reviewView(block).verdict).toBe('blocked');
        expect(flaggedOnCard(block)).toBe(false);
    });

    test('a malformed override is NOT an override, and the block stands unexcused', () => {
        for (const bad of [{}, { by: 'someone' }, { reason: '' }, { reason: '  ' }, { reason: 7 }, 'yes', 42, [], null]) {
            const view = reviewView(reviewed({
                verdict: 'blocked',
                warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
                override: bad,
            }));
            expect(view.overridden, JSON.stringify(bad)).toBe(false);
            expect(view.overrideReason, JSON.stringify(bad)).toBe(null);
            expect(view.overrideBy, JSON.stringify(bad)).toBe(null);
            expect(view.overrideAt, JSON.stringify(bad)).toBe(null);
            expect(view.verdict, JSON.stringify(bad)).toBe('blocked');
        }
    });

    test('a readable reason with no by or an unreadable at attributes nothing', () => {
        const noBy = reviewView(reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
            override: { reason: 'internal fixture', at: '2026-09-19T00:00:00Z' },
        }));
        expect(noBy.overrideReason).toBe('internal fixture');
        expect(noBy.overrideBy).toBe(null);
        expect(noBy.overrideAt).toBe('2026-09-19');

        const badAt = reviewView(reviewed({
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
            override: { reason: 'internal fixture', by: 'acme', at: 'not-a-date' },
        }));
        expect(badAt.overrideReason).toBe('internal fixture');
        expect(badAt.overrideBy).toBe('acme');
        expect(badAt.overrideAt).toBe(null);
    });

    test('NEGATIVE CONTROL: no override at all reports none', () => {
        const view = reviewView(reviewed({ verdict: 'clean', warnings: [] }));
        expect(view.overridden).toBe(false);
        expect(view.overrideReason).toBe(null);
        expect(view.overrideBy).toBe(null);
        expect(view.overrideAt).toBe(null);
    });
});

describe('nothing in here ever throws', () => {
    test('the hostile set is answered, not raised on', () => {
        const hostile: unknown[] = [
            { status: 'reviewed', verdict: 'clean', warnings: 'not a list' },
            { status: 'reviewed', verdict: {}, warnings: [null, undefined, 7] },
            { status: 'reviewed', verdict: 'blocked', warnings: [{ kind: null, detail: null }] },
            { status: {}, verdict: [] },
            [],
            'a string',
            0,
        ];
        for (const input of hostile) {
            expect(() => reviewView(input as never)).not.toThrow();
            expect(reviewView(input as never).verdict).not.toBe('clean');
        }
    });
});

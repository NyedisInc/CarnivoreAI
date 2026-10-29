import { describe, expect, test } from 'vitest';

import { cardView, latestVersion } from './card';
import { workingDirOf } from './catalog';
import { reviewLabel } from '../../../../client/js/labels/skill.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('absent renders absent, and zero is not absent', () => {
    test('an item with nothing on it emits no fact at all', () => {
        const card = cardView({}, false);
        expect(card.id).toBe(null);
        expect(card.name).toBe(null);
        expect(card.headline).toBe(null);
        expect(card.brief).toBe(null);
        expect(card.publisher).toBe(null);
        expect(card.version).toBe(null);
        expect(card.tags).toBe(null);
        expect(card.scripts).toBe(null);
        expect(card.reviewStatus).toBe(null);
        expect(card.reviewSummary).toBe(null);
        expect(card.warnings).toBe(null);
    });

    test('a COUNTED zero survives, because `|| null` would eat it', () => {
        const card = cardView(
            { latest: '1.0', versions: [{ v: '1.0', scripts: 0 }] },
            false,
        );
        expect(card.scripts).toBe(0);
        expect(card.marksScripts).toBe(false);
    });

    test('a whitespace-only name is the same case as no name', () => {
        const card = cardView({ id: 'a/b', name: '   ' }, false);
        expect(card.name).toBe(null);
        expect(card.headline).toBe('a/b');
    });
});

describe('the scripts marker', () => {
    test('a positive count marks', () => {
        const card = cardView({ latest: '2', versions: [{ v: '2', scripts: 3 }] }, false);
        expect(card.scripts).toBe(3);
        expect(card.marksScripts).toBe(true);
    });

    test('zero does not mark', () => {
        const card = cardView({ latest: '2', versions: [{ v: '2', scripts: 0 }] }, false);
        expect(card.marksScripts).toBe(false);
    });

    test('and an ABSENT count does not mark either', () => {
        const card = cardView({ latest: '2', versions: [{ v: '2' }] }, false);
        expect(card.scripts).toBe(null);
        expect(card.marksScripts).toBe(false);
    });
});

describe('a machine review that did not run', () => {
    test('the status is carried through as its own value', () => {
        const card = cardView(
            { latest: '1', versions: [{ v: '1', review: { status: 'unavailable' } }] },
            false,
        );
        expect(card.reviewStatus).toBe('unavailable');
    });

    test('and it renders as NO AI REVIEW, never as a finding', () => {
        const label = reviewLabel('unavailable', t);
        expect(label).toBe('no ai review');
        expect(label).not.toContain('nothing detected');
        expect(label).not.toContain('detected');
        expect(label).not.toContain('clean');
    });

    test('a review that DID run says so, and differently', () => {
        expect(reviewLabel('reviewed', t)).toBe('ai reviewed');
        expect(reviewLabel('reviewed', t)).not.toBe(reviewLabel('unavailable', t));
    });

    test('no review block at all renders NOTHING, which is a third case', () => {
        expect(reviewLabel(null, t)).toBe(null);
        expect(reviewLabel(undefined, t)).toBe(null);
        const card = cardView({ latest: '1', versions: [{ v: '1' }] }, false);
        expect(card.reviewStatus).toBe(null);
    });

    test('warnings are COUNTED from the list, and an empty list counts zero', () => {
        const some = cardView(
            {
                latest: '1',
                versions: [{ v: '1', review: { status: 'reviewed', warnings: [{}, {}] } }],
            },
            false,
        );
        expect(some.warnings).toBe(2);
        const none = cardView(
            { latest: '1', versions: [{ v: '1', review: { status: 'reviewed', warnings: [] } }] },
            false,
        );
        expect(none.warnings).toBe(0);
    });
});

describe('the latest version is the one the index pointed at', () => {
    test('matched by its own `v`, wherever it sits in the array', () => {
        const item = { latest: '2.0', versions: [{ v: '1.0' }, { v: '2.0', scripts: 9 }] };
        expect(latestVersion(item)?.scripts).toBe(9);
        expect(cardView(item, false).scripts).toBe(9);
    });

    test('A GUESS NEVER OUTRANKS A RECORD: no match is no version', () => {
        const item = { latest: '9.9', versions: [{ v: '1.0', scripts: 4 }] };
        expect(latestVersion(item)).toBe(null);
        const card = cardView(item, false);
        expect(card.scripts).toBe(null);
        expect(card.marksScripts).toBe(false);
        expect(card.version).toBe('9.9');
    });

    test('and no `latest` at all resolves nothing', () => {
        expect(latestVersion({ versions: [{ v: '1.0' }] })).toBe(null);
        expect(latestVersion(null)).toBe(null);
    });
});

describe('the headline ladder and the untrusted flag', () => {
    test('title, then name, then id, and every rung is recorded', () => {
        expect(cardView({ id: 'p/s', name: 's', card: { title: 'T' } }, false).headline).toBe('T');
        expect(cardView({ id: 'p/s', name: 's' }, false).headline).toBe('s');
        expect(cardView({ id: 'p/s' }, false).headline).toBe('p/s');
    });

    test('untrusted comes from WHICH LIST the server put it in', () => {
        expect(cardView({ id: 'a' }, true).untrusted).toBe(true);
        expect(cardView({ id: 'a' }, false).untrusted).toBe(false);
    });

    test('tags are carried as the index listed them', () => {
        expect(cardView({ card: { tags: ['a', 'b'] } }, false).tags).toEqual(['a', 'b']);
        expect(cardView({ card: {} }, false).tags).toBe(null);
    });
});

describe('the project seed reads the level the field is actually on', () => {
    test('the nested working_dir is what seeds the picker', () => {
        expect(workingDirOf({ session: { working_dir: '/a/b' } })).toBe('/a/b');
    });

    test('the WRAPPER level is not read, because the field is not there', () => {
        expect(workingDirOf({ working_dir: '/a/b' })).toBe(null);
    });

    test('absent is null, and null is not a failure', () => {
        expect(workingDirOf(null)).toBe(null);
        expect(workingDirOf({})).toBe(null);
        expect(workingDirOf({ session: {} })).toBe(null);
        expect(workingDirOf({ session: { working_dir: '   ' } })).toBe(null);
    });
});

describe('the kind is carried, and never defaulted', () => {
    test('a theme says so, and the badge gate is the exact string', () => {
        const card = cardView({ id: 'a/neon', kind: 'theme' }, false);
        expect(card.kind).toBe('theme');
        expect(card.isTheme).toBe(true);
    });

    test('a skill is not a theme', () => {
        const card = cardView({ id: 'a/sme', kind: 'skill' }, false);
        expect(card.kind).toBe('skill');
        expect(card.isTheme).toBe(false);
    });

    test('an ABSENT kind stays absent rather than becoming a skill', () => {
        const card = cardView({ id: 'a/x' }, false);
        expect(card.kind).toBe(null);
        expect(card.isTheme).toBe(false);
    });

    test('a plugin says so, and the badge gate is the exact string', () => {
        const card = cardView({ id: 'a/toolbelt', kind: 'plugin' }, false);
        expect(card.kind).toBe('plugin');
        expect(card.isPlugin).toBe(true);
        expect(card.isTheme).toBe(false);
    });

    test('a theme is not a plugin, and a skill is neither', () => {
        expect(cardView({ id: 'a/neon', kind: 'theme' }, false).isPlugin).toBe(false);
        const skill = cardView({ id: 'a/sme', kind: 'skill' }, false);
        expect(skill.isPlugin).toBe(false);
        expect(skill.isTheme).toBe(false);
    });

    test('a kind this build cannot name is carried, not rewritten', () => {
        const card = cardView({ id: 'a/x', kind: 'bundle' }, false);
        expect(card.kind).toBe('bundle');
        expect(card.isTheme).toBe(false);
        expect(card.isPlugin).toBe(false);
        expect(card.isLoadout).toBe(false);
    });

    test('the fourth kind is recognised and the other three are not it', () => {
        const loadout = cardView({ id: 'a/python', kind: 'loadout' }, false);
        expect(loadout.isLoadout).toBe(true);
        expect(loadout.isTheme).toBe(false);
        expect(loadout.isPlugin).toBe(false);
        expect(cardView({ id: 'a/sme', kind: 'skill' }, false).isLoadout).toBe(false);
        expect(cardView({ id: 'a/neon', kind: 'theme' }, false).isLoadout).toBe(false);
    });
});

describe('the published quality grade reaches the row, and never a second opinion', () => {
    test('a measured grade reaches the card view', () => {
        const card = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: 'A', checked: 12, failed: [] } }] },
            false,
        );
        expect(card.gradeShape).toBe('graded');
        expect(card.gradeLetter).toBe('A');
    });

    test('NEGATIVE CONTROL: a version with no grade block claims nothing', () => {
        const card = cardView({ latest: '1.0', versions: [{ v: '1.0' }] }, false);
        expect(card.gradeShape).toBe('absent');
        expect(card.gradeLetter).toBe(null);
    });

    test('NEGATIVE CONTROL: ungraded is not a letter', () => {
        const card = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: 'ungraded' } }] },
            false,
        );
        expect(card.gradeShape).toBe('ungraded');
        expect(card.gradeLetter).toBe(null);
    });

    test('a failing skill keeps its letter', () => {
        const card = cardView(
            {
                latest: '1.0',
                versions: [
                    {
                        v: '1.0',
                        grade: {
                            grade: 'D',
                            checked: 12,
                            failed: [
                                {
                                    rule: 'description.length',
                                    level: 'required',
                                    detail: 'description is 1059 characters, over the 1024 the specification allows',
                                },
                            ],
                        },
                    },
                ],
            },
            false,
        );
        expect(card.gradeLetter).toBe('D');
    });

    test('the grade is read off the LATEST version, not the first', () => {
        const card = cardView(
            {
                latest: '2.0',
                versions: [
                    { v: '1.0', grade: { grade: 'F', checked: 12, failed: [] } },
                    { v: '2.0', grade: { grade: 'A', checked: 12, failed: [] } },
                ],
            },
            false,
        );
        expect(card.gradeLetter).toBe('A');
    });
});

describe('whether the row is marked for the security verdict', () => {
    const rowFor = (review: unknown) =>
        cardView({ latest: '1', versions: [{ v: '1', review }] } as never, false);

    test('a flagged verdict marks the row', () => {
        const card = rowFor({
            status: 'reviewed',
            verdict: 'flagged',
            warnings: [{ kind: 'network', detail: 'd', file: 'SKILL.md' }],
        });
        expect(card.flagged).toBe(true);
    });

    test('a blocked verdict marks it; an overridden one paints no verdict and no flag', () => {
        const plain = rowFor({
            status: 'reviewed',
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
        });
        const excused = rowFor({
            status: 'reviewed',
            verdict: 'blocked',
            warnings: [{ kind: 'obfuscation', detail: 'd', file: 'SKILL.md' }],
            override: { reason: 'internal fixture' },
        });
        expect(plain.flagged).toBe(true);
        expect(excused.flagged).toBe(false);
        expect(excused.verdict).toBeNull();
        expect(plain.verdict).toBe('blocked');
    });

    test('a verdict this build cannot read marks it, because it is not clean', () => {
        expect(rowFor({ status: 'reviewed', verdict: 'clen', warnings: [] }).flagged).toBe(true);
    });

    test('NEGATIVE CONTROL: a clean verdict marks NOTHING', () => {
        expect(rowFor({ status: 'reviewed', verdict: 'clean', warnings: [] }).flagged).toBe(false);
    });

    test('NEGATIVE CONTROL: no verdict at all marks nothing either', () => {
        expect(rowFor({ status: 'reviewed', warnings: [] }).flagged).toBe(false);
        expect(rowFor({ status: 'unavailable' }).flagged).toBe(false);
        expect(cardView({ latest: '1', versions: [{ v: '1' }] }, false).flagged).toBe(false);
    });

    test('the warnings COUNT and the verdict are separate facts', () => {
        const card = rowFor({ status: 'reviewed', warnings: [{ kind: 'network', detail: 'd' }] });
        expect(card.warnings).toBe(1);
        expect(card.flagged).toBe(false);
    });
});

describe('the hero image hash (S2 of #1342)', () => {
    const sha = 'a'.repeat(64);
    test('a 64-hex hash is kept; anything else, and an absent block, is null', () => {
        expect(cardView({ card: { media: { sha256: sha } } }, false).mediaSha).toBe(sha);
        expect(cardView({ card: { media: { sha256: sha.toUpperCase() } } }, false).mediaSha).toBeNull();
        expect(cardView({ card: { media: { sha256: 'https://evil.example/x.webp' } } }, false).mediaSha).toBeNull();
        expect(cardView({ card: { media: 'x' as never } }, false).mediaSha).toBeNull();
        expect(cardView({ card: {} }, false).mediaSha).toBeNull();
    });
});

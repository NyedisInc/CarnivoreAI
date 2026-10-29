import { describe, expect, test } from 'vitest';

import { loadoutFacts, memberFact, parseLoadoutManifest } from './loadout-facts';
import type { LoadoutMemberPreview } from './types';

const MANIFEST = JSON.stringify({
    schema: 'carnivore.catalog.loadout/1',
    name: 'python',
    description: 'the python working set',
    members: [{ id: 'alex/sme', version: '1.0.0', digest: 'a'.repeat(64) }],
});

const MEMBERS: LoadoutMemberPreview[] = [
    { item_id: 'alex/sme', version: '1.0.0', kind: 'skill', title: 'sme', scripts: 0 },
    {
        item_id: 'alex/toolbelt',
        version: '2.0.0',
        kind: 'plugin',
        title: 'toolbelt',
        scripts: 2,
    },
    {
        item_id: 'alex/neon',
        version: '1.1.0',
        kind: 'theme',
        title: 'neon',
        scripts: 0,
        installed: true,
    },
];

describe('identity comes from the manifest', () => {
    test('the name and description are read off the document', () => {
        const facts = loadoutFacts(MANIFEST, []);
        expect(facts.name).toBe('python');
        expect(facts.description).toBe('the python working set');
    });

    test('a manifest that does not parse still leaves the members alone', () => {
        const facts = loadoutFacts('{not json', MEMBERS);
        expect(facts.name).toBe(null);
        expect(facts.description).toBe(null);
        expect(facts.members.length).toBe(3);
    });

    test.each([['[]'], ['null'], ['"a string"'], [''], ['   ']])(
        'a manifest that is not an object answers null (%s)',
        (text) => {
            expect(parseLoadoutManifest(text)).toBe(null);
        },
    );
});

describe('membership comes from the server, never from the list', () => {
    test('every resolved member is carried, in order', () => {
        const facts = loadoutFacts(MANIFEST, MEMBERS);
        expect(facts.members.map((m) => m.itemId)).toEqual([
            'alex/sme',
            'alex/toolbelt',
            'alex/neon',
        ]);
        expect(facts.members.map((m) => m.version)).toEqual(['1.0.0', '2.0.0', '1.1.0']);
    });

    test('a member with no id is dropped rather than painted blank', () => {
        expect(memberFact({ version: '1.0.0' })).toBe(null);
        expect(memberFact(null)).toBe(null);
        expect(loadoutFacts(MANIFEST, [{ version: '1.0.0' }]).members.length).toBe(0);
    });

    test('a member with no title falls back to its id, never to nothing', () => {
        const fact = memberFact({ item_id: 'alex/x', version: '1.0.0' });
        expect(fact?.title).toBe('alex/x');
    });
});

describe('the two facts a consent surface turns on', () => {
    test('a counted, positive script count means this member needs a tick', () => {
        const facts = loadoutFacts(MANIFEST, MEMBERS);
        expect(facts.members.length).toBe(3);
        expect(facts.members[1]?.needsScripts).toBe(true);
        expect(facts.anyScripts).toBe(true);
    });

    test('a counted zero is not the same as nobody counting', () => {
        expect(memberFact({ item_id: 'a/x', scripts: 0 })?.needsScripts).toBe(false);
        expect(memberFact({ item_id: 'a/x' })?.needsScripts).toBe(false);
        expect(memberFact({ item_id: 'a/x', scripts: null })?.needsScripts).toBe(false);
        expect(memberFact({ item_id: 'a/x', scripts: 1 })?.needsScripts).toBe(true);
    });

    test('installed is a positive, explicit true and nothing else', () => {
        expect(memberFact({ item_id: 'a/x', installed: true })?.installed).toBe(true);
        expect(memberFact({ item_id: 'a/x' })?.installed).toBe(false);
        expect(memberFact({ item_id: 'a/x', installed: null })?.installed).toBe(false);
    });

    test('a theme among the members is what raises the "not applied" note', () => {
        expect(loadoutFacts(MANIFEST, MEMBERS).anyTheme).toBe(true);
        expect(
            loadoutFacts(MANIFEST, [
                { item_id: 'a/x', kind: 'skill', version: '1.0.0' },
            ]).anyTheme,
        ).toBe(false);
    });
});

describe('nothing is invented when there is nothing to report', () => {
    test('no manifest and no members is empty, not a throw', () => {
        const facts = loadoutFacts(null, null);
        expect(facts.name).toBe(null);
        expect(facts.members).toEqual([]);
        expect(facts.anyScripts).toBe(false);
        expect(facts.anyTheme).toBe(false);
    });

    test('NEGATIVE CONTROL: the parser really can read a good document', () => {
        // would pass for the wrong reason
        expect(parseLoadoutManifest(MANIFEST)).not.toBe(null);
        expect(loadoutFacts(MANIFEST, MEMBERS).name).toBe('python');
    });
});

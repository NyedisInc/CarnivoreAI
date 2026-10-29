import { describe, expect, test } from 'vitest';

import {
    SWATCH_TOKENS,
    isSafeColour,
    parseThemeManifest,
    themeFacts,
} from './theme-swatch';

function manifest(extra: Record<string, unknown>): string {
    return JSON.stringify({ id: 'neon', name: 'Neon', ...extra });
}

describe('only a closed set of colour literals may be painted', () => {
    test.each([
        ['#fff', 'three hex digits'],
        ['#ffff', 'four, with alpha'],
        ['#00ff41', 'six'],
        ['#00ff41cc', 'eight, with alpha'],
        ['#00FF41', 'upper case hex'],
        ['rgb(0, 255, 65)', 'rgb'],
        ['rgba(0, 255, 65, 0.5)', 'rgba'],
        ['rgb(0% 50% 100%)', 'percentages'],
        ['  #00ff41  ', 'surrounding space is trimmed, not rejected'],
    ])('accepts %s (%s)', (value) => {
        expect(isSafeColour(value)).toBe(true);
    });

    test.each([
        ['url(https://example.com/a.png)', 'a url is a FETCH, not a colour'],
        ['var(--color-bg)', 'a var reads a value this sheet did not vet'],
        ['red', 'a named colour is not in the whitelist'],
        ['#00ff41; background: url(x)', 'escapes the declaration with a semicolon'],
        ['#00ff41}', 'escapes the rule with a brace'],
        ['#00ff41 /* x */', 'carries a comment'],
        ['#gggggg', 'not hex digits'],
        ['#12345', 'five digits is not a hex colour'],
        ['rgb(0, 255, 65) url(x)', 'a trailing token after a valid prefix'],
        ['expression(alert(1))', 'legacy css expression'],
        ['', 'empty'],
        ['   ', 'blank'],
    ])('refuses %s (%s)', (value) => {
        expect(isSafeColour(value)).toBe(false);
    });

    test('refuses a value too long to be a colour', () => {
        expect(isSafeColour('#' + 'a'.repeat(200))).toBe(false);
    });

    test.each([[null], [undefined], [42], [{}], [[]], [true]])(
        'refuses the non-string %s',
        (value) => {
            expect(isSafeColour(value)).toBe(false);
        },
    );
});

describe('a manifest that cannot be read yields nothing, and never throws', () => {
    test.each([
        ['not json at all'],
        ['{"unclosed": '],
        ['[]'],
        ['"a string"'],
        ['null'],
        [''],
        ['   '],
    ])('parses %s to null', (text) => {
        expect(parseThemeManifest(text)).toBe(null);
    });

    test.each([[null], [undefined]])('parses the absent value %s to null', (text) => {
        expect(parseThemeManifest(text)).toBe(null);
    });

    test('an object parses to an object', () => {
        expect(parseThemeManifest('{"id":"neon"}')).toEqual({ id: 'neon' });
    });

    test('an unreadable manifest yields no facts at all', () => {
        const facts = themeFacts('not json');
        expect(facts.name).toBe(null);
        expect(facts.swatches).toEqual([]);
        expect(facts.effects).toBe(null);
    });
});

describe('the swatch strip is bounded, ordered, and drops what it cannot prove', () => {
    test('reads the recognised tokens in the module order, not the manifest order', () => {
        const facts = themeFacts(
            manifest({
                cssVars: {
                    '--color-accent': '#7f5af0',
                    '--color-bg': '#101014',
                    '--color-fg': '#e8e8f0',
                },
            }),
        );
        expect(facts.swatches.map((s) => s.token)).toEqual([
            '--color-bg',
            '--color-fg',
            '--color-accent',
        ]);
        expect(facts.swatches[0]?.value).toBe('#101014');
    });

    test('a token this build does not show is not painted', () => {
        const facts = themeFacts(
            manifest({ cssVars: { '--color-badge-tmux-bg': '#123456' } }),
        );
        expect(facts.swatches).toEqual([]);
    });

    test('an UNSAFE value is dropped while its safe neighbours survive', () => {
        const facts = themeFacts(
            manifest({
                cssVars: {
                    '--color-bg': 'url(https://example.com/x.png)',
                    '--color-fg': '#e8e8f0',
                },
            }),
        );
        expect(facts.swatches.map((s) => s.token)).toEqual(['--color-fg']);
    });

    test('the strip can never be longer than the token list', () => {
        const every: Record<string, string> = {};
        for (const token of SWATCH_TOKENS) every[token] = '#000000';
        every['--color-extra'] = '#ffffff';
        expect(themeFacts(manifest({ cssVars: every })).swatches.length).toBe(
            SWATCH_TOKENS.length,
        );
    });

    test('cssVars that is not an object yields no swatches', () => {
        expect(themeFacts(manifest({ cssVars: 'nope' })).swatches).toEqual([]);
        expect(themeFacts(manifest({ cssVars: ['#fff'] })).swatches).toEqual([]);
        expect(themeFacts(manifest({})).swatches).toEqual([]);
    });
});

describe('the name and the script are reported, never guessed', () => {
    test('a declared name and script are carried through', () => {
        const facts = themeFacts(manifest({ effects: 'effects.js' }));
        expect(facts.name).toBe('Neon');
        expect(facts.effects).toBe('effects.js');
    });

    test('NO script declared is null, which is what silences the warning', () => {
        expect(themeFacts(manifest({})).effects).toBe(null);
    });

    test.each([[''], ['   '], [42], [null]])(
        'a script field of %s is null rather than a name',
        (effects) => {
            expect(themeFacts(manifest({ effects })).effects).toBe(null);
        },
    );

    test('a blank name is absent rather than an empty heading', () => {
        expect(themeFacts(JSON.stringify({ id: 'neon', name: '   ' })).name).toBe(null);
    });
});

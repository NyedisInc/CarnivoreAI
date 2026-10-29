import { describe, expect, test } from 'vitest';

import {
    ACCOUNT_COLORS,
    STATUS_HUES,
    hueOf,
    hueDistance,
    isAccountColor,
    isStorableColor,
    lightnessOf,
    normaliseColorInput,
    swatchLabelKey,
} from './account-colors';

function familyOf(name: string): string {
    return name.split('_')[0] as string;
}

describe('the palette itself', () => {
    test('there are twenty four swatches', () => {
        expect(ACCOUNT_COLORS).toHaveLength(24);
    });

    test('the list is frozen, so nothing can push a twenty fifth onto it', () => {
        expect(Object.isFrozen(ACCOUNT_COLORS)).toBe(true);
    });

    test('every hex is lowercase six digits, which is what the server takes', () => {
        for (const swatch of ACCOUNT_COLORS) {
            expect(swatch.hex).toMatch(/^#[0-9a-f]{6}$/);
        }
    });

    test('no two swatches are the same colour', () => {
        const hexes = ACCOUNT_COLORS.map((swatch) => swatch.hex);
        expect(new Set(hexes).size).toBe(hexes.length);
    });

    test('every swatch has its own name, so the picker can be read aloud', () => {
        const names = ACCOUNT_COLORS.map((swatch) => swatch.name);
        expect(new Set(names).size).toBe(names.length);
    });

    test('the original eight are still the first eight, hex for hex and name for name', () => {
        expect(ACCOUNT_COLORS.slice(0, 8)).toEqual([
            { hex: '#a3e635', name: 'lime' },
            { hex: '#2dd4bf', name: 'teal' },
            { hex: '#818cf8', name: 'indigo' },
            { hex: '#a78bfa', name: 'violet' },
            { hex: '#c084fc', name: 'purple' },
            { hex: '#e879f9', name: 'orchid' },
            { hex: '#ef5fd8', name: 'magenta' },
            { hex: '#f472b6', name: 'pink' },
        ]);
    });
});

describe('hueOf reads a hex the way a screen does', () => {
    test('pure red is 0', () => {
        expect(hueOf('#ff0000')).toBe(0);
    });

    test('pure green is 120', () => {
        expect(hueOf('#00ff00')).toBe(120);
    });

    test('pure blue is 240', () => {
        expect(hueOf('#0000ff')).toBe(240);
    });

    test('grey has no hue and answers null rather than zero', () => {
        expect(hueOf('#8b8b8b')).toBeNull();
    });
});

describe('lightnessOf is the second axis the tones are told apart on', () => {
    test('black is nothing and white is everything', () => {
        expect(lightnessOf('#000000')).toBe(0);
        expect(lightnessOf('#ffffff')).toBe(1);
    });

    test('a mid grey is a half, even though it has no hue at all', () => {
        expect(lightnessOf('#808080')).toBeCloseTo(0.502, 2);
    });

    test('a value that is not lowercase six digit hex answers null rather than throwing', () => {
        expect(lightnessOf('nonsense')).toBeNull();
        expect(lightnessOf(null)).toBeNull();
    });
});

describe('hueDistance is measured the short way round the wheel', () => {
    test('ten degrees apart across zero is ten, not three hundred and fifty', () => {
        expect(hueDistance(355, 5)).toBe(10);
    });

    test('opposite sides of the wheel are a hundred and eighty', () => {
        expect(hueDistance(0, 180)).toBe(180);
    });
});

describe('no swatch is a status light', () => {
    const LED_HEXES = ['#4ade80', '#fbbf24', '#4fc1ff', '#8b8b8b', '#ff4444'];

    test('none of the five hexes is in the palette', () => {
        const hexes = ACCOUNT_COLORS.map((swatch) => swatch.hex);
        for (const led of LED_HEXES) {
            expect(hexes).not.toContain(led);
        }
    });

    test('the hues this module guards against are the four chromatic ones', () => {
        expect(STATUS_HUES).toHaveLength(4);
    });

    test('every swatch is at least 25 degrees from every status hue', () => {
        for (const swatch of ACCOUNT_COLORS) {
            const hue = hueOf(swatch.hex);
            expect(hue).not.toBeNull();
            for (const led of STATUS_HUES) {
                expect([swatch.name, hueDistance(hue as number, led) >= 25]).toEqual([
                    swatch.name,
                    true,
                ]);
            }
        }
    });

    test('no swatch is grey, so none of them can read as idle', () => {
        for (const swatch of ACCOUNT_COLORS) {
            expect(hueOf(swatch.hex)).not.toBeNull();
        }
    });
});

describe('the swatches can be told apart from each other', () => {
    const families = new Map<string, { hex: string; name: string }[]>();
    for (const swatch of ACCOUNT_COLORS) {
        const key = familyOf(swatch.name);
        const members = families.get(key) ?? [];
        members.push(swatch);
        families.set(key, members);
    }

    test('there are eight families and each one has three tones', () => {
        expect(families.size).toBe(8);
        for (const [name, members] of families) {
            expect([name, members.length]).toEqual([name, 3]);
        }
    });

    test('the three tones of one family really are the same hue', () => {
        for (const [name, members] of families) {
            const hues = members.map((swatch) => hueOf(swatch.hex) as number);
            for (const hue of hues) {
                expect([name, hueDistance(hue, hues[0] as number) <= 1]).toEqual([name, true]);
            }
        }
    });

    test('the tones of one family are far enough apart in lightness to tell apart', () => {
        for (const [name, members] of families) {
            const levels = members
                .map((swatch) => lightnessOf(swatch.hex) as number)
                .sort((left, right) => left - right);
            for (let index = 1; index < levels.length; index += 1) {
                const gap = (levels[index] as number) - (levels[index - 1] as number);
                expect([name, gap >= 0.1]).toEqual([name, true]);
            }
        }
    });

    test('no tone is so dark it disappears into a dark theme', () => {
        for (const swatch of ACCOUNT_COLORS) {
            expect([swatch.name, (lightnessOf(swatch.hex) as number) >= 0.3]).toEqual([
                swatch.name,
                true,
            ]);
        }
    });

    test('two different families are at least 12 degrees of hue apart', () => {
        const hues = [...families.entries()]
            .map(([name, members]) => ({ name, hue: hueOf((members[0] as { hex: string }).hex) as number }))
            .sort((left, right) => left.hue - right.hue);
        for (let index = 1; index < hues.length; index += 1) {
            const before = hues[index - 1] as { name: string; hue: number };
            const after = hues[index] as { name: string; hue: number };
            expect([before.name, after.name, hueDistance(before.hue, after.hue) >= 12]).toEqual([
                before.name,
                after.name,
                true,
            ]);
        }
    });
});

describe('isAccountColor asks whether the palette carries this colour', () => {
    const first = ACCOUNT_COLORS[0] as { hex: string; name: string };

    test('a swatch this palette ships is accepted', () => {
        expect(isAccountColor(first.hex)).toBe(true);
    });

    test('a tone added in the twenty four is accepted too', () => {
        const deep = ACCOUNT_COLORS.find((swatch) => swatch.name.endsWith('_deep'));
        expect(isAccountColor(deep?.hex)).toBe(true);
    });

    test('a hex that is not in the palette is refused', () => {
        expect(isAccountColor('#123456')).toBe(false);
    });

    test('an uppercase spelling of a swatch is refused, as the server refuses it', () => {
        expect(isAccountColor(first.hex.toUpperCase())).toBe(false);
    });

    test('null is refused, because no colour is not a colour', () => {
        expect(isAccountColor(null)).toBe(false);
    });

    test('anything that is not a string is refused without throwing', () => {
        expect(isAccountColor(7 as unknown as string)).toBe(false);
    });
});

describe('isStorableColor asks the different question the free picker needs', () => {
    test('a colour the palette never offered is storable, which is the whole point', () => {
        expect(isStorableColor('#123456')).toBe(true);
        expect(isAccountColor('#123456')).toBe(false);
    });

    test('every swatch the palette ships is storable as well', () => {
        for (const swatch of ACCOUNT_COLORS) {
            expect([swatch.name, isStorableColor(swatch.hex)]).toEqual([swatch.name, true]);
        }
    });

    test('an uppercase spelling is refused, because the server refuses it', () => {
        expect(isStorableColor('#ABCDEF')).toBe(false);
    });

    test('three digit shorthand is refused, because the server takes six', () => {
        expect(isStorableColor('#abc')).toBe(false);
    });

    test('a hex with no hash is refused', () => {
        expect(isStorableColor('abcdef')).toBe(false);
    });

    test('null is refused, because no colour is a separate answer from a colour', () => {
        expect(isStorableColor(null)).toBe(false);
        expect(isStorableColor(undefined)).toBe(false);
    });

    test('anything that is not a string is refused without throwing', () => {
        expect(isStorableColor(7 as unknown as string)).toBe(false);
    });
});

describe('normaliseColorInput is what the free picker hands the form', () => {
    test('an uppercase spelling comes back lowercase rather than refused', () => {
        expect(normaliseColorInput('#AABBCC')).toBe('#aabbcc');
    });

    test('a value already lowercase is handed back unchanged', () => {
        expect(normaliseColorInput('#123456')).toBe('#123456');
    });

    test('surrounding whitespace is taken off, because it is not a choice', () => {
        expect(normaliseColorInput('  #123456 ')).toBe('#123456');
    });

    test('a value that is not a colour answers null rather than a guess', () => {
        expect(normaliseColorInput('#abc')).toBeNull();
        expect(normaliseColorInput('rebeccapurple')).toBeNull();
        expect(normaliseColorInput('')).toBeNull();
    });

    test('null and undefined answer null, so an empty input sends nothing', () => {
        expect(normaliseColorInput(null)).toBeNull();
        expect(normaliseColorInput(undefined)).toBeNull();
    });

    test('anything that is not a string answers null without throwing', () => {
        expect(normaliseColorInput(7 as unknown as string)).toBeNull();
    });
});

describe('swatchLabelKey', () => {
    const first = ACCOUNT_COLORS[0] as { hex: string; name: string };

    test('a swatch answers its own catalog key', () => {
        expect(swatchLabelKey(first.hex)).toBe(`ledger.color.${first.name}`);
    });

    test('every swatch answers a key under ledger.color', () => {
        for (const swatch of ACCOUNT_COLORS) {
            expect(swatchLabelKey(swatch.hex)).toBe(`ledger.color.${swatch.name}`);
        }
    });

    test('a colour the palette does not carry answers the custom key', () => {
        expect(swatchLabelKey('#123456')).toBe('ledger.color.custom');
    });
});

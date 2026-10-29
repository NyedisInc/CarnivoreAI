import { describe, expect, it } from 'vitest';
import { boundedDistance, highlightSegments, parseQuery, scoreTexts } from './fuzzy-search';

const hits = (q: string, ...texts: string[]): boolean => scoreTexts(parseQuery(q), texts) > 0;

describe('parseQuery', () => {
    it('lower-cases, splits on punctuation and drops repeats', () => {
        expect(parseQuery('Shift  update-shift')).toEqual(['shift', 'update']);
    });
    it('is empty for a blank query', () => {
        expect(parseQuery('   ')).toEqual([]);
    });
});

describe('boundedDistance', () => {
    it('counts a swap of neighbours as one edit', () => {
        expect(boundedDistance('chnage', 'change', 2)).toBe(1);
    });
    it('gives up past the limit', () => {
        expect(boundedDistance('abcdef', 'uvwxyz', 2)).toBe(3);
    });
});

describe('scoreTexts', () => {
    it('finds a typo: "keychan" finds keychain', () => {
        expect(hits('keychan', 'reads the macOS keychain once')).toBe(true);
    });
    it('finds a swap and a missing letter', () => {
        expect(hits('chnage', 'a change to the row')).toBe(true);
        expect(hits('updte', 'the update icon')).toBe(true);
    });
    it('is word-order tolerant: "shift update" finds "update icon shift"', () => {
        expect(hits('shift update', 'the update icon moves when shift is held')).toBe(true);
        expect(hits('update shift', 'shift held, then the update icon')).toBe(true);
    });
    it('needs every token', () => {
        expect(hits('shift banana', 'the update icon shift')).toBe(false);
    });
    it('matches across several texts', () => {
        expect(hits('shift keychain', 'the shift key', 'keychain access')).toBe(true);
    });
    it('gives 0 for no tokens', () => {
        expect(scoreTexts([], ['anything'])).toBe(0);
    });
    it('exact outranks prefix outranks substring outranks typo', () => {
        const s = (text: string) => scoreTexts(['chain'], [text]);
        expect(s('chain')).toBeGreaterThan(s('chained'));
        expect(s('chained')).toBeGreaterThan(s('keychain'));
        expect(s('keychain')).toBeGreaterThan(s('chian'));
    });
});

describe('short queries do not produce false positives', () => {
    it('a one or two letter token matches only a word start', () => {
        expect(hits('a', 'table')).toBe(false);
        expect(hits('ab', 'table')).toBe(false);
        expect(hits('ta', 'table')).toBe(true);
    });
    it('a two letter token gets no typo tolerance', () => {
        expect(hits('tb', 'table')).toBe(false);
    });
    it('a three letter token is a substring at most, never a typo match', () => {
        expect(hits('abl', 'table')).toBe(true);
        expect(hits('tbl', 'table')).toBe(false);
    });
    it('a four letter token tolerates one edit, not two', () => {
        expect(hits('tabl', 'tables')).toBe(true);
        expect(hits('xxbl', 'table')).toBe(false);
    });
});

describe('highlightSegments', () => {
    it('marks the whole word for a typo match and leaves the rest plain', () => {
        expect(highlightSegments('the keychain', ['keychan'])).toEqual([
            { text: 'the ', hit: false },
            { text: 'keychain', hit: true },
        ]);
    });
    it('marks only the matched part for a prefix', () => {
        expect(highlightSegments('updates', ['upd'])).toEqual([
            { text: 'upd', hit: true },
            { text: 'ates', hit: false },
        ]);
    });
    it('returns one plain run with no hit and never touches markup characters', () => {
        expect(highlightSegments('<b>x</b>', ['zzzz'])).toEqual([{ text: '<b>x</b>', hit: false }]);
    });
    it('keeps every character: segments join back to the text', () => {
        const text = 'Shift + update, then Update!';
        expect(highlightSegments(text, ['update', 'shift']).map((s) => s.text).join('')).toBe(text);
    });
});

describe('plain mode (the changelog default) versus fuzzy', () => {
    const texts = ['the page opens', 'a nice place', 'more space here', 'keep the PACE steady'];
    const hits = (query: string, mode: 'plain' | 'fuzzy'): string[] =>
        texts.filter((text) => scoreTexts(parseQuery(query), [text], mode) > 0);

    it('"pace" in plain mode matches only text containing "pace", case-insensitively', () => {
        expect(hits('pace', 'plain')).toEqual(['more space here', 'keep the PACE steady']);
        expect(hits('PaCe', 'plain')).toEqual(['more space here', 'keep the PACE steady']);
    });

    it('"pace" in fuzzy mode also finds the one-edit neighbours page and place', () => {
        expect(hits('pace', 'fuzzy')).toEqual(texts);
    });

    it('plain mode has no typo tolerance and no length floor for substrings', () => {
        expect(scoreTexts(parseQuery('keycha'), ['macOS keychain'], 'plain')).toBeGreaterThan(0);
        expect(scoreTexts(parseQuery('keychian'), ['macOS keychain'], 'plain')).toBe(0);
        expect(scoreTexts(parseQuery('keychian'), ['macOS keychain'], 'fuzzy')).toBeGreaterThan(0);
        expect(scoreTexts(parseQuery('ab'), ['a table'], 'plain')).toBeGreaterThan(0);
        expect(scoreTexts(parseQuery('ab'), ['a table'], 'fuzzy')).toBe(0);
    });

    it('plain mode still needs every token, in any order', () => {
        expect(scoreTexts(parseQuery('shift update'), ['update icon shift'], 'plain')).toBeGreaterThan(0);
        expect(scoreTexts(parseQuery('shift missing'), ['update icon shift'], 'plain')).toBe(0);
    });

    it('plain mode highlights only the exact part, never a typo neighbour', () => {
        expect(highlightSegments('the page in space', ['pace'], 'plain')).toEqual([
            { text: 'the page in s', hit: false },
            { text: 'pace', hit: true },
        ]);
        expect(highlightSegments('the page', ['pace'], 'fuzzy').some((s) => s.hit && s.text === 'page')).toBe(true);
    });
});

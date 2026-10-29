import { describe, expect, test } from 'vitest';
import { snippetParts } from './snippet-parts';

describe('snippetParts', () => {
    test('splits on the two control characters into text and match pieces', () => {
        expect(snippetParts('fixed the \u0002flux\u0003 \u0002capacitor\u0003 today')).toEqual([
            { text: 'fixed the ', match: false },
            { text: 'flux', match: true },
            { text: ' ', match: false },
            { text: 'capacitor', match: true },
            { text: ' today', match: false },
        ]);
    });

    test('markup in a snippet stays text, and an unclosed or stray marker never throws', () => {
        expect(snippetParts('<img src=x onerror=1> \u0002<b>hit</b>\u0003')).toEqual([
            { text: '<img src=x onerror=1> ', match: false },
            { text: '<b>hit</b>', match: true },
        ]);
        expect(snippetParts('a \u0002open')).toEqual([{ text: 'a ', match: false }, { text: 'open', match: true }]);
        expect(snippetParts('')).toEqual([]);
        expect(snippetParts('\u0003 lone close')).toEqual([{ text: ' lone close', match: false }]);
    });
});

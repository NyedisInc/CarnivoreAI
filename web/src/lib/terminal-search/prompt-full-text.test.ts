import { describe, expect, it } from 'vitest';

import { matchFullTexts } from './prompt-full-text';
import { RailModel } from './rail-model.svelte';
import type { RailPrompt } from './types';

describe('matchFullTexts (issue #1277)', () => {
    it('returns the whole multi-paragraph prompt for its scanned first paragraph', () => {
        const got = matchFullTexts([{ ordinal: 1, text: 'fix the bug' }], ['fix the bug\n\nthen add a test']);
        expect(got.get(1)).toBe('fix the bug\n\nthen add a test');
    });

    it('keeps two prompts sharing a first paragraph distinct, by order', () => {
        const transcript = ['same start\n\nfirst ending', 'same start\n\nsecond ending'];
        const got = matchFullTexts(
            [{ ordinal: 1, text: 'same start' }, { ordinal: 2, text: 'same start' }],
            transcript,
        );
        expect(got.get(1)).toBe(transcript[0]);
        expect(got.get(2)).toBe(transcript[1]);
    });

    it('drops reply lines a blank-less scan picked up, and aligns on the newest prompts', () => {
        const got = matchFullTexts(
            [{ ordinal: 1, text: 'do it now sure thing here' }],
            ['older one', 'do it now'],
        );
        expect(got.get(1)).toBe('do it now');
    });

    it('leaves an unmatched prompt out so the scanned text stays', () => {
        expect(matchFullTexts([{ ordinal: 1, text: 'nothing like it' }], ['other']).size).toBe(0);
    });
});

describe('RailModel.fullTextOf', () => {
    function rail(promptTexts?: () => Promise<string[] | null>): RailModel {
        const r = new RailModel({ term: () => null, promptScan: () => null, isRule: () => undefined, promptTexts });
        r.prompts = [{ ordinal: 1, line: 0, text: 'a b', full: 'a b', preview: 'a b', marker: null, matches: true } as RailPrompt];
        return r;
    }

    it('answers the transcript text, and null on no hook, an empty list or a rejection', async () => {
        expect(await rail(async () => ['a b\n\nc']).fullTextOf(1)).toBe('a b\n\nc');
        expect(await rail().fullTextOf(1)).toBeNull();
        expect(await rail(async () => []).fullTextOf(1)).toBeNull();
        expect(await rail(async () => { throw new Error('x'); }).fullTextOf(1)).toBeNull();
    });
});

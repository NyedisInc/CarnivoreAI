import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { modelColorKey } from './model-color';

describe('modelColorKey', () => {
    const cases: Array<[unknown, string]> = [
        ['Gemini 4 Neon', 'neon'], ['gemini-4-carbon', 'carbon'], ['Gemini 4 Argon', 'argon'], ['Gemini 4 Hydrogen', 'hydrogen'],
        ['claude-fable-5-2', 'fable'], ['Fable 5.2', 'fable'], ['claude-opus-5-5', 'opus'], ['claude-sonnet-5-5', 'sonnet'],
        ['claude-haiku-5-5', 'haiku'], ['gpt-6-sol', ''], [null, ''],
    ];
    it.each(cases)('%s -> %s', (text, key) => expect(modelColorKey(text)).toBe(key));

    it('the legacy client/js helper answers the same for every case', () => {
        const win: Record<string, unknown> = {};
        runInNewContext(readFileSync('../client/js/session-model-icon.js', 'utf8'), { window: win, console: { log() {} } });
        const icon = win.SessionModelIcon as { colorKey(t: unknown): string };
        for (const [text, key] of cases) expect(icon.colorKey(text)).toBe(key);
    });
});

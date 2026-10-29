import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';
import { cssRules } from '../base/css-rules';

const src = readFileSync(resolve(__dirname, 'LaunchProfilesScreen.svelte'), 'utf8');
const rules = cssRules(src.slice(src.indexOf('<style'), src.indexOf('</style>')));
const rule = (sel: string) => rules.find((r) => r.selector === sel)?.decls ?? {};

describe('launch profile row subtitle', () => {
    test('the sub line wraps so the badge goes below before the facts are cut', () => {
        expect(rule('.lp-item__sub')['flex-wrap']).toBe('wrap');
    });
    test('the facts keep a readable floor width and still ellipsize past it', () => {
        const facts = rule('.lp-item__facts');
        expect(facts['flex']).toMatch(/^1 1 \d+ch$/);
        expect(facts['text-overflow']).toBe('ellipsis');
    });
});

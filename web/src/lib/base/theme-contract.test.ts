import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { expect, test } from 'vitest';

import { THEME_CONTRACT, checkThemeVars } from './theme-contract';

const THEMES_DIR = new URL('../../../../client/css/themes/', import.meta.url);

test('every bundled theme keeps the contract', () => {
    const ids = readdirSync(THEMES_DIR).filter((d) => existsSync(new URL(`${d}/theme.json`, THEMES_DIR)));
    expect(ids.length).toBeGreaterThanOrEqual(12);
    for (const id of ids) {
        const vars = JSON.parse(readFileSync(new URL(`${id}/theme.json`, THEMES_DIR), 'utf8')).cssVars ?? {};
        const r = checkThemeVars(vars);
        expect({ id, unknown: r.unknown, baseTokens: r.baseTokens, missing: r.missing, badValues: r.badValues })
            .toEqual({ id, unknown: [], baseTokens: [], missing: [], badValues: [] });
    }
});

test('negative control: each break is named', () => {
    const required = Object.fromEntries(
        Object.entries(THEME_CONTRACT.names).filter(([, s]) => s.required).map(([n]) => [n, '#000000']),
    );
    const planted: Record<string, string> = { ...required, '--oc-space-3': '20px', '--my-glow': 'red', '--radius-control': '6px', '--radius-sm': '2px' };
    delete planted['--color-fg'];
    const r = checkThemeVars(planted);
    expect(r).toEqual({
        unknown: ['--my-glow'], baseTokens: ['--oc-space-3'], deprecated: ['--radius-sm'], missing: ['--color-fg'],
        badValues: ['--radius-control: above 4px'],
    });
    expect(checkThemeVars(required)).toEqual({ unknown: [], baseTokens: [], deprecated: [], missing: [], badValues: [] });
});

import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';

const css = readFileSync(new URL('./timeline.css', import.meta.url), 'utf8');

test('every --led-color a band reads is declared on .sp-tl', () => {
    const used = new Set([...css.matchAll(/var\((--led-color-[a-z]+)\)/g)].map((m) => m[1]));
    expect(used.size).toBeGreaterThan(0);
    const root = /\n\s{4}\.sp-tl \{([^}]*)\}/.exec(css)?.[1] ?? '';
    for (const name of used) expect(root).toContain(`${name}:`);
});

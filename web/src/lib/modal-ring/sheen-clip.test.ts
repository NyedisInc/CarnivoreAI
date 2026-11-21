import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const CSS = readFileSync(resolve(__dirname, '../../../../client/css/modal-glow.css'), 'utf8');

function sheenHostBlock(css: string): string {
    const start = css.indexOf('.modal-content > .mg-sheen,');
    expect(start, 'the sheen host rule exists').toBeGreaterThan(-1);
    const open = css.indexOf('{', start);
    return css.slice(open + 1, css.indexOf('}', open));
}

describe('dialog ring sheen host (#2950)', () => {
    it('clips the turning square so it never adds scrollable overflow to the overlay', () => {
        expect(sheenHostBlock(CSS)).toMatch(/overflow:\s*(hidden|clip)\s*;/);
    });
});

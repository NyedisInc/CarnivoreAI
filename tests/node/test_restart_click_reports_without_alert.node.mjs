import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');
const src = (f) => fs.readFileSync(path.join(JS, f), 'utf8');

test('neither module calls native alert()', () => {
    for (const f of ['../../web/src/lib/drawer/restart-click.ts', 'slash-favorites.js']) {
        assert.doesNotMatch(src(f).replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ''), /\balert\(/, `${f} still calls alert()`);
    }
});

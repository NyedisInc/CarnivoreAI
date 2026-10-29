
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const STALE = /(two weeks old|two-week wait|two-week minimum|at least two weeks|Electron \(44\.x\)|44\.x pin)/i;

function staleLines(text) {
    return text.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => STALE.test(l)).map(([i, l]) => `${i}: ${l.trim()}`);
}

assert.equal(staleLines('9. Shell: Electron (44.x), one Chromium').length, 1);
assert.equal(staleLines('newest Electron stable that is\n   at least two weeks old, bumped').length, 1);

const desk = fs.readFileSync(path.join(root, 'docs', 'desktop-app.md'), 'utf8');
assert.ok(/Electron/.test(desk), 'desktop-app.md read but names no Electron');

const files = ['desktop-app.md', 'mac-auto-update.md'];
for (const f of files) {
    const hits = staleLines(fs.readFileSync(path.join(root, 'docs', f), 'utf8'))
        .filter((l) => !/existed only to get past the two-week wait/.test(l));
    assert.deepEqual(hits, [], `docs/${f} still states the retired Electron age rule`);
}
console.log('ok test_electron_pin_docs');

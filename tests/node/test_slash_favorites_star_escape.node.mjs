import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'slash-favorites.js'), 'utf8');

test('a quote in a command name stays inside data-fav-toggle and aria-label', () => {
    const sandbox = { console: { log() {} }, document: { createElement: () => { let t = ''; return { set textContent(v) { t = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }, get innerHTML() { return t; } }; } } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox);
    const html = sandbox.window.SlashFavorites.starButton('/x" onmouseover="alert(1)', false);
    assert.doesNotMatch(html, /" onmouseover="/, 'the quote must be escaped');
    assert.match(html, /data-fav-toggle="\/x&quot; onmouseover=&quot;alert\(1\)"/);
});

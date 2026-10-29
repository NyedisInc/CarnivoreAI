import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');
const FILES = ['header-title-fit.js', 'header-menu.js', 'screen-chrome.js', 'server-restart-watch.js'];

function runTwice(src) {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    vm.createContext(sandbox);
    const errors = [];
    for (let i = 0; i < 2; i += 1) {
        try { vm.runInContext(src, sandbox); } catch (e) { errors.push(e); }
    }
    return { sandbox, errors };
}

for (const file of FILES) {
    test(`${file} declares nothing at global scope`, () => {
        const src = fs.readFileSync(path.join(JS, file), 'utf8');
        const { sandbox, errors } = runTwice(src);
        const leaked = [...src.matchAll(/^(?:function|var)\s+(\w+)/gm)].map((m) => m[1]).filter((n) => n in sandbox);
        assert.deepEqual(leaked, [], 'top-level function/var leaked onto the global');
        const redeclared = errors.filter((e) => e instanceof SyntaxError || /already been declared/.test(String(e)));
        assert.deepEqual(redeclared.map(String), [], 'a second load must not hit a redeclaration error');
    });
}

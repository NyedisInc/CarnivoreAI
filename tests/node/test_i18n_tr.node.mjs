import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client/js/i18n/tr.js'), 'utf8');

function load(extra = {}) {
    const ctx = { ...extra };
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return ctx;
}

assert.equal(load().CloudeTr('some.key', { a: 1 }), 'some.key');
const late = load();
late.CloudeI18n = { t: (k, p) => `${k}:${p && p.a}` };
assert.equal(late.CloudeTr('x', { a: 2 }), 'x:2');
assert.equal(load({ CloudeI18n: {} }).CloudeTr('k'), 'k');
console.log('ALL PASS');

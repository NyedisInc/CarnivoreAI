import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { makeEnv } from '../../lib_toast_dom_stub.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('STRICT: a sibling that redefines an existing ToastManager method throws and names the file and the method', () => {
    const { mgr, run } = makeEnv();
    const before = mgr.add;
    run('globalThis.__EXTEND_PROTOTYPE_STRICT__ = true;');
    assert.throws(
        () => run('extendPrototype(ToastManager, { add() { return "shadow"; } }, "fixture-sibling.js");'),
        (err) => /fixture-sibling\.js/.test(err.message) && /\badd\b/.test(err.message),
    );
    assert.equal(mgr.add, before, 'the original method must still be the one on the prototype');
});

test('NON-STRICT: a clash keeps the first definition, still assigns the other names and reports once', () => {
    const { mgr, run } = makeEnv();
    const before = mgr.add;
    const seen = [];
    const realError = console.error;
    console.error = (m) => seen.push(m);
    try {
        run('globalThis.__EXTEND_PROTOTYPE_STRICT__ = false;'
            + 'extendPrototype(ToastManager, { add() { return "shadow"; }, extraOne() { return 1; } }, "fixture-sibling.js");');
    } finally { console.error = realError; }
    assert.equal(mgr.add, before, 'first definition kept');
    assert.equal(mgr.extraOne(), 1, 'the non-clashing name was still assigned');
    assert.equal(seen.length, 1);
    assert.match(seen[0], /fixture-sibling\.js.*\badd\b/);
});

test('a sibling that adds only new names is accepted', () => {
    const { mgr, run } = makeEnv();
    run('extendPrototype(ToastManager, { brandNewMethod() { return 7; } }, "fixture-sibling.js");');
    assert.equal(mgr.brandNewMethod(), 7);
});

test('NEGATIVE CONTROL: no shipped client/js file patches a prototype with a raw Object.assign', () => {
    const dir = path.join(ROOT, 'client', 'js');
    const raw = /^\s*Object\.assign\(\s*[A-Za-z_$][\w$]*\.prototype\s*,/m;
    const offenders = fs.readdirSync(dir).filter((f) => f.endsWith('.js') && f !== 'extend-prototype.js' && raw.test(fs.readFileSync(path.join(dir, f), 'utf8')));
    assert.deepEqual(offenders, [], `raw Object.assign(X.prototype, ...) left in: ${offenders.join(', ')}`);
});

test('the shipped siblings load together with no collision (makeEnv runs all of them)', () => {
    const { mgr } = makeEnv();
    for (const name of ['add', 'dismiss', '_render', '_groups', 'backfill']) assert.equal(typeof mgr[name], 'function', name);
});

let failed = 0;
for (const [name, fn] of tests) {
    try { await fn(); console.log(`ok   ${name}`); } catch (err) { failed += 1; console.log(`FAIL ${name}\n     ${err && err.stack}`); }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);

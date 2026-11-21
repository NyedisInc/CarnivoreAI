import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'client/index.html'), 'utf8');
const files = [...html.matchAll(/src="\/static\/js\/(extend-prototype\.js|api(?:-[a-z-]+)?\.js)"/g)].map((m) => m[1]);
assert.ok(files.includes('api.js') && files.includes('extend-prototype.js'), 'index.html script scan found nothing');
assert.ok(files.length >= 14, `expected api.js, extend-prototype.js and 12 api-*.js, got ${files.length}`);

const ctx = {
    console, setTimeout, clearTimeout, location: { protocol: 'http:', host: 'x' }, fetch: async () => ({}),
    localStorage: { getItem() { return null; }, setItem() {} }, document: { addEventListener() {}, cookie: '' },
    addEventListener() {}, navigator: {}, __EXTEND_PROTOTYPE_STRICT__: true,
};
ctx.window = ctx; ctx.globalThis = ctx; vm.createContext(ctx);
const errors = [];
for (const f of files) {
    try { vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js', f), 'utf8'), ctx, { filename: f }); }
    catch (err) { errors.push(`${f}: ${err.message}`); }
}
assert.deepEqual(errors, [], `prototype clashes in page order:\n${errors.join('\n')}`);
console.log(`ok   ${files.length} files loaded in page order with no clash\n\n1/1 passed`);

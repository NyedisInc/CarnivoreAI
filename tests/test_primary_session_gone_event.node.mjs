import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const EVENT = 'cloude:primary-session-gone';

let passes = 0;
let failures = 0;
function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

test('the compiled tree exports the literal', () => {
    const src = fs.readFileSync(
        path.join(ROOT, 'web/src/opscenter/cells/terminal-group/tab-controller.svelte.ts'), 'utf8');
    assert.match(src, /export const PRIMARY_SESSION_GONE_EVENT = 'cloude:primary-session-gone';/);
});

test('terminal.js dispatches the same literal from the page-owner 4404 path', () => {
    const src = fs.readFileSync(path.join(ROOT, 'client/js/terminal.js'), 'utf8');
    assert.ok(src.includes(`new CustomEvent('${EVENT}', { detail: { tmuxName } })`),
        'terminal.js must dispatch the literal with the gone tmux name as detail');
});

test('row-menu-sleep.ts dispatches the same literal from releaseThisTab', () => {
    const src = fs.readFileSync(path.join(ROOT, 'web/src/lib/drawer/row-menu-sleep.ts'), 'utf8');
    assert.ok(src.includes(`new CustomEvent('${EVENT}', { detail: { tmuxName: ctx.name } })`),
        'row-menu-sleep.ts must dispatch the literal with the gone tmux name as detail');
});

console.log(`${passes} passed, ${failures} failed`);
if (failures || passes === 0) process.exit(1);

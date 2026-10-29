
import assert from 'node:assert/strict';

import { makeEnv, toast, cards } from './lib_toast_dom_stub.mjs';

const MOON_PATH_SIGNATURE = 'M13.3 9.3A6 6 0 0 1 6.7 2.7a6 6 0 1 0 6.6 6.6z';

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('the AutoSlept toast title is prefixed with the reused moon icon', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('AutoSlept', 'session put to sleep', 'slept api after 60 min idle'));
    const card = cards(container)[0];
    const title = card.querySelector('.toast__title');
    const icon = title.querySelector('.toast__title-icon');
    assert.ok(icon, 'the AutoSlept card must carry a .toast__title-icon');
    assert.ok(String(icon.innerHTML).includes(MOON_PATH_SIGNATURE),
        'the icon must be the REUSED SessionRowMenuIcons sleep glyph, not a new one');
    assert.ok(String(icon.innerHTML).includes('stroke="currentColor"'),
        'the glyph must paint with currentColor, never a hardcoded color');
    const iconIdx = title.childNodes.indexOf(icon);
    const textIdx = title.childNodes.indexOf(title.querySelector('.toast__title-text'));
    assert.ok(iconIdx < textIdx, 'the icon must sit before the title text');
    assert.equal(title.querySelector('.toast__title-text').textContent, 'session put to sleep');
});

test('a DIFFERENT toast kind gets no icon at all', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('PermissionRequest', 'permission needed', 'claude wants to run: npm install'));
    const card = cards(container)[0];
    assert.equal(card.querySelector('.toast__title-icon'), null,
        'only the AutoSlept toast gets the moon prefix; nothing else changes');
});

test('a Notification toast (the closest neighbour in severity) also gets no icon', () => {
    const { container, mgr } = makeEnv();
    mgr.add(toast('Notification', 'claude is waiting', null));
    const card = cards(container)[0];
    assert.equal(card.querySelector('.toast__title-icon'), null,
        'Notification must not pick up the AutoSlept-only icon');
});


let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log(`ok   ${name}`);
    } catch (err) {
        failed += 1;
        console.log(`FAIL ${name}\n     ${err && err.message}`);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);

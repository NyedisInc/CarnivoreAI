
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

import { test, results } from './lib-home-mechanics.mjs';
// SLICE 3: the session data layer lives in the compiled bundle, and the
// `Launchpad` fields this harness drives are accessors over that one
// store. The REAL client/dist/app.js is evaluated in this sandbox rather
// than stubbed, so these assertions run against the shipped path.
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

function loadStatusUI() {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    installCloudeWeb(sandbox);
    for (const f of ['status-led.js', 'session-status-ui.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(ROOT, 'client', 'js', f), 'utf8'),
            sandbox,
            { filename: f },
        );
    }
    assert.ok(sandbox.StatusLed, 'status-led.js did not publish StatusLed');
    return sandbox.SessionStatusUI;
}


// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

await test('the mark-unread control is pressed from the same field', () => {
    const ui = loadStatusUI();
    assert.match(ui.markUnreadHtml('cloude_oneflag', true), /aria-pressed="true"/);
    assert.match(ui.markUnreadHtml('cloude_oneflag', false), /aria-pressed="false"/);
    assert.match(ui.markUnreadHtml('cloude_oneflag', true), /data-unread-current="true"/);
});

const { passes, failures } = results();
console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);

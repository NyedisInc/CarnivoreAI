
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');

let passes = 0;
let failures = 0;

async function test(name, fn) {
    try {
        await fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

const NOTICE = path.join(repoRoot, 'client', 'js', 'write-failure-notice.js');
const TOAST = path.join(repoRoot, 'client', 'js', 'toast.js');

function reportOne(withManager = true) {
    const cards = [];
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    if (withManager) sandbox.ToastManager = { WRITE_FAILED_KIND: 'WriteFailed', add: (record) => cards.push(record) };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(NOTICE, 'utf8'), sandbox, { filename: NOTICE });
    sandbox.WriteFailureNotice.report('could not create the group: refused');
    return cards;
}

await test('the card carries what a card needs: local, no session, a named surface', () => {
    const cards = reportOne();
    assert.equal(cards.length, 1, 'no card was raised');
    const card = cards[0];
    assert.equal(card.local, true, 'not marked local: dismissing would ack an id no server minted');
    assert.equal(card.session_id, null, 'a session id would fold this into a conversation card');
    assert.ok(card.session_label, 'no identity line: the card would claim "unknown session"');
    assert.equal(card.kind, 'WriteFailed');
    assert.ok(card.id && String(card.id).length > 8, 'no usable record id');
});

await test('NEGATIVE CONTROL: with no toast manager the notice raises nothing rather than pretending', () => {
    assert.deepEqual(reportOne(false), []);
});

await test('the kind is registered CAP-EXEMPT, so a failure cannot hide behind "+2 more"', () => {
    const toast = fs.readFileSync(TOAST, 'utf8');
    const kind = /const WRITE_FAILED_KIND = '([^']+)'/.exec(toast);
    assert.ok(kind, 'toast.js does not declare the write-failure kind');
    assert.equal(kind[1], 'WriteFailed');
    const exempt = /const CAP_EXEMPT_SEVERITY = (\d+)/.exec(toast);
    assert.ok(exempt, 'toast.js no longer declares a cap-exempt threshold');
    const severity = /\[WRITE_FAILED_KIND\]:\s*(\d+)/.exec(toast);
    assert.ok(severity, 'the write-failure kind has no severity, so it takes the default');
    assert.ok(Number(severity[1]) >= Number(exempt[1]),
        `severity ${severity[1]} is below the cap exemption ${exempt[1]}: a failed write could become invisible again`);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');

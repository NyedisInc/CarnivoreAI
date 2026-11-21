import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const src = fs.readFileSync(new URL('../../client/js/paste-prompt-hint.js', import.meta.url), 'utf8');

function load(shell) {
    const sandbox = { carnivoreShell: shell };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.runInNewContext(src, sandbox);
    return sandbox.PastePromptHint;
}

const ios = load({ version: 1, platform: 'ios' });
const browser = load(undefined);
const T = ios.PROMPT_THRESHOLD_MS;

assert.equal(ios.wasForcedToPrompt(T, false), true, 'a read at the threshold is a prompt');
assert.equal(ios.wasForcedToPrompt(2400, false), true, 'a slow allowed read is a prompt');
assert.equal(ios.wasForcedToPrompt(20, false), false, 'a fast read is not');
assert.equal(ios.wasForcedToPrompt(20, true), true, 'a refusal is a prompt however fast');
assert.equal(browser.wasForcedToPrompt(5000, true), false, 'never outside the native shell');
assert.equal(load({ platform: 'mac' }).wasForcedToPrompt(5000, true), false, 'never in a non-ios shell');
assert.equal(ios.isRefusal({ name: 'NotAllowedError' }), true);
assert.equal(ios.isRefusal(new Error('x')), false);
assert.equal(ios.isRefusal(null), false);
console.log('paste-prompt-hint: all passed');

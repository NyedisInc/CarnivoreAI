// underneath.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks the test failed.
 * @returns {void}
 */
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

/**
 * Read one file from the repo root.
 * @param {...string} parts  Path segments below the repo root.
 * @returns {string} File contents.
 */
function read(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');
}

function stripComments(source) {
    return source.replace(/\/\*[\s\S]*?\*\//g, '')
        .split('\n')
        .filter((line) => !/^\s*\/\//.test(line))
        .join('\n');
}

const registrySrc = stripComments(read('web', 'src', 'lib', 'settings-page', 'settings-registry.ts'));

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('the settings page declares no agents section', () => {
    assert.ok(!/id:\s*'agents'/.test(registrySrc), 'an agents section is back in SETTINGS_SECTIONS');
});

test('no setting of the page edits a legacy command key directly', () => {
    assert.ok(!/_command'/.test(registrySrc),
        'a <family>_command field is declared in settings-registry.ts');
    assert.ok(!/group:\s*'agents'/.test(registrySrc),
        'an agents-group field is declared in settings-registry.ts');
    assert.ok(!/panel:\s*'agent-commands'/.test(registrySrc),
        'the legacy agent-commands panel is back in settings-registry.ts');
    assert.ok(/id:\s*'agent_commands'[^\n]*kind:\s*'link'[^\n]*action:\s*'open-wrappers'/.test(registrySrc),
        'the link row to the wrappers page, the settings page\'s only reference to these keys, is gone');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);

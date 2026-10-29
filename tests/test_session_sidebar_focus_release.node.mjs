
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

async function runQueue() {
    for (const [name, fn] of queue) {
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
}

test('both terminal-arrival paths hand focus to the terminal', () => {
    const src = readClientJs('app.js');
    assert.match(src, /focusTerminal\(\)\s*\{/,
        'App.focusTerminal() must exist');
    assert.match(src, /querySelector\('\.xterm-helper-textarea'\)/,
        'and must target the terminal input xterm actually creates');

    function methodBody(name) {
        const asyncAt = src.indexOf(`\n    async ${name}(`);
        const start = asyncAt >= 0 ? asyncAt : src.indexOf(`\n    ${name}(`);
        assert.ok(start >= 0, `${name} must exist in app.js`);
        const end = src.indexOf('\n    }\n', start);
        assert.ok(end > start, `${name} must have a class-level terminator`);
        return src.slice(start, end);
    }

    for (const name of ['showTerminal', 'returnToExistingTerminal']) {
        assert.match(methodBody(name), /this\.focusTerminal\(\)/,
            `${name}() must hand focus to the terminal - otherwise whatever the `
            + 'user clicked to get here keeps it and swallows their keystrokes');
    }
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');

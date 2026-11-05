import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const JS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');

const KNOWN = new Set(['session-status-summary.js', 'terminal-key-bar.js', 'terminal-mascot.js']);

export function offenders(files) {
    return [...files].filter(([, text]) => text.includes('CloudeI18n')).map(([name]) => name).sort();
}

function readClientScripts(dir = JS_DIR, prefix = '') {
    const files = new Map();
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const rel = prefix + entry.name;
        if (entry.isDirectory()) {
            if (rel === 'i18n') continue;
            for (const [name, text] of readClientScripts(path.join(dir, entry.name), rel + '/')) files.set(name, text);
        } else if (entry.name.endsWith('.js')) {
            files.set(rel, fs.readFileSync(path.join(dir, entry.name), 'utf8'));
        }
    }
    return files;
}

const scripts = readClientScripts();
assert.ok(scripts.size > 50, 'the scan must look at the client scripts, not at nothing');
const bad = offenders(scripts).filter((name) => !KNOWN.has(name));
assert.deepEqual(bad, [], `use CloudeTr(key, params), not CloudeI18n: ${bad.join(', ')}`);
const stale = [...KNOWN].filter((name) => !offenders(scripts).includes(name));
assert.deepEqual(stale, [], `drop these rows from KNOWN: ${stale.join(', ')}`);
assert.deepEqual(offenders(new Map([['x.js', 'var i18n = globalThis.CloudeI18n;'], ['y.js', 'CloudeTr(k)']])), ['x.js']);
console.log('ALL PASS');

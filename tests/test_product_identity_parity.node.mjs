
import path from 'node:path';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const require = createRequire(import.meta.url);

const CONSTANT_NAMES = [
    'PRODUCT_NAME',
    'TMUX_SOCKET_NAME',
    'TMUX_SESSION_PREFIX',
    'DB_FILENAME',
    'DB_BACKUP_PREFIX',
    'STATE_DIR_NAME',
    'MENUBAR_STATE_DIR_NAME',
    'BUNDLE_ID',
    'ENV_PREFIX',
    'UPLOAD_DIR_NAME',
    'BROWSER_KEY_PREFIX',
    'RELEASE_REPO',
];

let failures = 0;
let passes = 0;
let skips = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes += 1;
        } catch (err) {
            if (err && err.skip) {
                skips += 1;
                console.log(`SKIP ${name}: ${err.message}`);
                continue;
            }
            failures += 1;
            console.error(`FAIL ${name}: ${err && err.message}`);
        }
    }
}

/** Mark the current test as skipped rather than passed. */
function skip(reason) {
    const e = new Error(reason);
    e.skip = true;
    throw e;
}

function pick(mod) {
    const out = {};
    for (const key of CONSTANT_NAMES) {
        out[key] = mod[key];
    }
    return out;
}

function pythonValues() {
    let python3;
    try {
        python3 = execFileSync('bash', ['-c', 'command -v python3'], { encoding: 'utf8' }).trim();
    } catch {
        skip('python3 is not on PATH; cannot verify against src/core/product_identity.py');
    }
    const code = [
        'import json',
        'from src.core import product_identity as pid',
        `names = ${JSON.stringify(CONSTANT_NAMES)}`,
        'print(json.dumps({n: getattr(pid, n) for n in names}))',
    ].join('\n');
    const out = execFileSync(python3, ['-c', code], { cwd: repoRoot, encoding: 'utf8' });
    return JSON.parse(out);
}

function shellValues() {
    const script = path.join(repoRoot, 'scripts', 'product-identity.sh');
    const command = [
        `source "${script}"`,
        `for v in ${CONSTANT_NAMES.join(' ')}; do printf "%s\\t%s\\n" "$v" "\${!v}"; done`,
    ].join('; ');
    const out = execFileSync('bash', ['-c', command], { cwd: repoRoot, encoding: 'utf8' });
    const values = {};
    for (const line of out.split('\n')) {
        if (!line) continue;
        const [name, value] = line.split('\t');
        values[name] = value;
    }
    return values;
}


const cjsMod = require(path.join(repoRoot, 'macOS', 'product-identity.js'));
const esmMod = await import(path.join(repoRoot, 'client', 'js', 'product-identity.js'));
const tsMod = await import(path.join(repoRoot, 'web', 'src', 'lib', 'product-identity.ts'));

const cjsValues = pick(cjsMod);
const esmValues = pick(esmMod);
const tsValues = pick(tsMod);

test('the CommonJS and ES module mirrors agree', () => {
    assert.deepStrictEqual(
        cjsValues,
        esmValues,
        'macOS/product-identity.js and client/js/product-identity.js have drifted apart'
    );
});

test('the ES module and TypeScript mirrors agree', () => {
    assert.deepStrictEqual(
        esmValues,
        tsValues,
        'client/js/product-identity.js and web/src/lib/product-identity.ts have drifted apart'
    );
});

test('the shell mirror agrees with the JS/TS mirrors', () => {
    const shell = shellValues();
    assert.deepStrictEqual(
        shell,
        esmValues,
        'scripts/product-identity.sh has drifted from the JS/TS mirrors'
    );
});

test('the Python source of truth agrees with every mirror', () => {
    let python;
    try {
        python = pythonValues();
    } catch (err) {
        if (err && err.skip) throw err;
        throw new Error(`could not read Python values: ${err && err.message}`);
    }
    assert.deepStrictEqual(python, cjsValues, 'Python disagrees with the CommonJS mirror');
    assert.deepStrictEqual(python, esmValues, 'Python disagrees with the ES module mirror');
    assert.deepStrictEqual(python, tsValues, 'Python disagrees with the TypeScript mirror');
});

test('every constant name is covered by all three JS/TS mirrors', () => {
    for (const name of CONSTANT_NAMES) {
        assert.ok(name in cjsMod, `macOS/product-identity.js is missing ${name}`);
        assert.ok(name in esmMod, `client/js/product-identity.js is missing ${name}`);
        assert.ok(name in tsMod, `web/src/lib/product-identity.ts is missing ${name}`);
    }
});

await runQueue();
console.log(`${passes} passed, ${failures} failed, ${skips} skipped`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');


import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');

function loadFamilyIcon() {
    const src = fs.readFileSync(
        path.join(repoRoot, 'client', 'js', 'agent-family-icon.js'), 'utf8');
    const ctx = { window: {}, console: { log() {} } };
    vm.createContext(ctx);
    vm.runInContext(src, ctx);
    return ctx.window.AgentFamilyIcon;
}

function serverFamilyNames() {
    const src = fs.readFileSync(
        path.join(repoRoot, 'src', 'core', 'agent_families.py'), 'utf8');
    const tableStart = src.indexOf('AGENT_FAMILIES: Tuple[AgentFamily, ...] = (');
    assert.notEqual(tableStart, -1, 'AGENT_FAMILIES table not found; agent_families.py was restructured');
    const tableEnd = src.indexOf('\n)\n', tableStart);
    const table = src.slice(tableStart, tableEnd === -1 ? undefined : tableEnd);
    const names = [...table.matchAll(/name="([a-z_]+)"/g)].map((m) => m[1]);
    assert.ok(names.length >= 5, `expected at least 5 families, parsed ${names.length}`);
    return names;
}

const FamilyIcon = loadFamilyIcon();
let failures = 0;
let passes = 0;

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

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('every server-side agent family has a client-side icon, and vice versa', () => {
    const serverNames = serverFamilyNames();
    const clientNames = [...FamilyIcon.FAMILIES];
    const serverSet = new Set(serverNames);
    const clientSet = new Set(clientNames);

    const missingOnClient = serverNames.filter((n) => !clientSet.has(n));
    const extraOnClient = clientNames.filter((n) => !serverSet.has(n) && n !== 'unknown');

    assert.deepEqual(missingOnClient, [],
        `agent_families.py names a family with no client icon: [${missingOnClient.join(', ')}] - ` +
        'every session of that family would silently draw the dashed "unknown" ring');
    assert.deepEqual(extraOnClient, [],
        `client/js/agent-family-icon.js draws a family the server does not have: [${extraOnClient.join(', ')}]`);
});

test('a family the parity check has never seen normalizes to "unknown", not a false match', () => {
    assert.equal(FamilyIcon.FAMILIES.includes('gemini'), false);
    assert.equal(FamilyIcon.normalize('gemini'), 'unknown');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const WRAPPER_TABLE = [
    { wrapperId: 'claude', family: 'claude', icon: 'claude' },
    { wrapperId: 'cld', family: 'claude', icon: 'claude' },
    { wrapperId: 'cldor', family: 'claude', icon: 'claude' },
    { wrapperId: 'claude-skip-permissions', family: 'claude', icon: 'claude' },
    { wrapperId: 'claude-chrome', family: 'claude', icon: 'claude' },
    { wrapperId: 'cldl', family: 'local', icon: 'local' },
    { wrapperId: '(reserved family) codex', family: 'codex', icon: 'codex' },
    { wrapperId: '(reserved family) hermes', family: 'hermes', icon: 'hermes' },
    { wrapperId: '(reserved family) openclaw', family: 'openclaw', icon: 'openclaw' },
    { wrapperId: '(reserved family) shell / terminal', family: 'shell', icon: 'shell' },
    { wrapperId: '(unresolvable / adopted)', family: null, icon: 'unknown' },
];

for (const { wrapperId, family, icon } of WRAPPER_TABLE) {
    test(`${wrapperId} (agent_family=${JSON.stringify(family)}) draws the "${icon}" mark`, () => {
        assert.equal(FamilyIcon.normalize(family), icon);
    });
}

test('every entry in the wrapper table maps to a DISTINCT icon from every other family', () => {
    const byFamily = new Map();
    for (const { family, icon } of WRAPPER_TABLE) {
        if (family === null) continue;
        if (byFamily.has(family)) {
            assert.equal(byFamily.get(family), icon, `${family} must map to one icon everywhere`);
        } else {
            byFamily.set(family, icon);
        }
    }
    assert.equal(new Set(byFamily.values()).size, byFamily.size, 'two different families share one icon key');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);

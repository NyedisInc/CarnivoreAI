// and it says so

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(__dirname, '..', 'macOS');

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


function loadManager(baseDir) {
    const source = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
    const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-menubar-ud-'));
    const electronStub = {
        app: {
            getPath: () => userData,
            getAppPath: () => baseDir,
            isPackaged: false,
            getVersion: () => '0.0.0-test',
        },
    };
    const nodeRequire = Module.createRequire(path.join(macDir, 'server-manager.js'));
    const requireShim = (name) => {
        if (name === 'electron') return electronStub;
        if (name === 'axios') return { get: async () => ({ data: {} }) };
        return nodeRequire(name);
    };

    const sandbox = {
        require: requireShim,
        module: { exports: {} },
        exports: {},
        __dirname: macDir,
        __filename: path.join(macDir, 'server-manager.js'),
        console,
        process,
        Buffer,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox, { filename: 'server-manager.js' });

    const ServerManager = sandbox.module.exports;
    const manager = new ServerManager();
    manager.baseDir = baseDir;
    return manager;
}

function fixture(config) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-menubar-'));
    if (config !== null) {
        fs.writeFileSync(path.join(dir, 'config.json'), JSON.stringify(config, null, 2));
    }
    return dir;
}

test('the tray reads the bind preference the settings screen wrote', () => {
    const dir = fixture({ server_prefs: { bind_host: '0.0.0.0' } });
    assert.equal(loadManager(dir).getBindHost(), '0.0.0.0');
});

test('a config with no server_prefs block expresses no preference', () => {
    const dir = fixture({ agents: {} });
    assert.equal(loadManager(dir).readConfigBindHost(), null);
});

test('an unreadable config is a could-not-read, not an answer', () => {
    const dir = fixture(null);
    fs.writeFileSync(path.join(dir, 'config.json'), '{ not json');
    assert.equal(loadManager(dir).readConfigBindHost(), null);
});

test('an empty stored value is not a preference either', () => {
    const dir = fixture({ server_prefs: { bind_host: '   ' } });
    assert.equal(loadManager(dir).readConfigBindHost(), null);
});

test('with no config preference the legacy menubar setting still wins', () => {
    const dir = fixture({ agents: {} });
    const manager = loadManager(dir);
    manager._settings.bind_host = '192.168.1.40';
    assert.equal(manager.getBindHost(), '192.168.1.40');
});

test('config.json beats the legacy setting when both are present', () => {
    const dir = fixture({ server_prefs: { bind_host: '127.0.0.1' } });
    const manager = loadManager(dir);
    manager._settings.bind_host = '0.0.0.0';
    assert.equal(manager.getBindHost(), '127.0.0.1');
});

test('writing the preference MERGES into config.json rather than replacing it', () => {
    const dir = fixture({
        agents: { codex_command: 'codex' },
        server_prefs: { tls_preferred: true },
    });
    const manager = loadManager(dir);
    assert.equal(manager.writeConfigBindHost('0.0.0.0'), true);

    const after = JSON.parse(fs.readFileSync(path.join(dir, 'config.json'), 'utf8'));
    assert.equal(after.server_prefs.bind_host, '0.0.0.0');
    assert.equal(after.server_prefs.tls_preferred, true, 'the TLS preference was lost');
    assert.equal(after.agents.codex_command, 'codex', 'an unrelated block was lost');
});

test('a write to a missing config reports failure instead of creating one', () => {
    const dir = fixture(null);
    assert.equal(loadManager(dir).writeConfigBindHost('0.0.0.0'), false);
});

test('no temp file is left behind by a successful write', () => {
    const dir = fixture({ server_prefs: {} });
    loadManager(dir).writeConfigBindHost('127.0.0.1');
    const stray = fs.readdirSync(dir).filter((f) => f.endsWith('.tmp'));
    assert.deepEqual([...stray], []);
});


const mainSrc = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
const serverActionsSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'server.js'), 'utf8');
const serverModelSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'server.js'), 'utf8');
const footerSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'footer.js'), 'utf8');

const mainCode = (mainSrc + serverActionsSrc)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !/^\s*\/\//.test(line))
    .join('\n');

test('Edit Config no longer reveals the file in Finder', () => {
    assert.ok(!/open -R/.test(mainCode), 'the menu still shells out to `open -R`');
});

test('Edit Config goes through the configured-editor helper', () => {
    assert.match(serverModelSrc, /act\('server\.edit_config', t\('menubar\.server\.edit_config'\), \{ kind: 'server\.edit_config' \}\)/);
    assert.match(serverActionsSrc, /'server\.edit_config':\s*\(\)\s*=>\s*openInConfiguredEditor\(/);
});

test('the editor helper reads workspace.default_editor', () => {
    const fn = serverActionsSrc.slice(
        serverActionsSrc.indexOf('function openInConfiguredEditor('),
        serverActionsSrc.indexOf('function tailServerLog(')
    );
    assert.match(fn, /workspace\.default_editor|workspace && parsed\.workspace/);
});

test('the editor helper falls back rather than becoming a dead menu item', () => {
    const fn = serverActionsSrc.slice(
        serverActionsSrc.indexOf('function openInConfiguredEditor('),
        serverActionsSrc.indexOf('function tailServerLog(')
    );
    assert.match(fn, /shell\.openPath/);
});

test('the editor helper says a hand edit needs a restart', () => {
    const fn = serverActionsSrc.slice(
        serverActionsSrc.indexOf('function openInConfiguredEditor('),
        serverActionsSrc.indexOf('function tailServerLog(')
    );
    assert.match(fn, /Restart the server after you save/);
});

test('the menu bar Settings item opens the app window at the settings route', () => {
    assert.match(footerSrc, /maybe\(up, 'settings', t\('menubar\.settings'\), \{ kind: 'app\.open', hash: '#settings' \}/);
    assert.ok(!/openWebSettings/.test(mainSrc + footerSrc), 'Settings must not open the external browser any more');
});

test('the menu bar names the carnivore account, or offers the sign-in that opens the account page', () => {
    assert.match(footerSrc, /t\('menubar\.settings\.signed_in', \{ login: account\.split\('@'\)\[0\] \}\)/);
    assert.match(footerSrc, /act\('account\.sign_in', t\('menubar\.account\.sign_in'\), \{ kind: 'app\.account' \}\)/);
    const appActions = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'app.js'), 'utf8');
    assert.match(appActions, /shell\.openExternal\(`\$\{base\}\/#account`\)/);
});


const appSrc = fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'app.js'), 'utf8');

test('the web app honours #settings and leaves it as the open page link', () => {
    const fn = appSrc.slice(
        appSrc.indexOf('_openSettingsIfDeepLinked() {'),
        appSrc.indexOf('setupEventListeners() {')
    );
    assert.match(fn, /#settings/);
    assert.doesNotMatch(fn, /history\.replaceState/);
    assert.match(fn, /CloudeWeb\.openSettingsScreen/);
});

test('the deep link is honoured from showLaunchpad, which BOTH login paths reach', () => {
    const fn = appSrc.slice(appSrc.indexOf('showLaunchpad() {'));
    // WINDOW WIDENED 2026-08-31. A fixed byte slice over a function
    // body is brittle: adding a comment inside showLaunchpad() pushes
    // the thing being asserted past the end and this reports a
    // FAILURE about the wrong subject entirely - the hook is still
    // there, the window just stopped covering it. Widened rather than
    // trimmed at the source, because shrinking a comment to fit a
    // test's magic number is fitting the code to the harness.
    assert.match(fn.slice(0, 8000), /_openSettingsIfDeepLinked\(\)/);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);

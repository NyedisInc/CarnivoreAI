import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const REPO = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const js = (f) => fs.readFileSync(path.join(REPO, 'client', 'js', f), 'utf8');

function setup() {
    const revoked = [];
    let minted = 0;
    const manifest = JSON.parse(fs.readFileSync(path.join(REPO, 'client', 'css', 'themes', 'carnivore', 'theme.json'), 'utf8'));
    manifest.source = 'builtin';
    const host = { style: { backgroundImage: '' }, dataset: {} };
    const sandbox = {
        console, Math, JSON, isFinite, parseFloat, String, Object, Promise, Error, encodeURIComponent,
        document: { documentElement: { dataset: {} }, querySelector: () => null, getElementById: () => null, addEventListener() {}, dispatchEvent: () => true },
        MutationObserver: function () { return { observe() {}, disconnect() {} }; },
        CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
        URL: { createObjectURL: () => `blob:${++minted}`, revokeObjectURL: (u) => revoked.push(u) },
        Themes: { listAll: () => [manifest], getActiveTerminalManifest: () => manifest, onXtermThemeChange: () => () => {} },
        API: {
            fetchSessionBackgroundImage: async () => ({}),
            uploadSessionBackgroundImage: async () => ({ theme_id: null, dim: null, disabled: false, image: 's.png' }),
            deleteSessionBackgroundImage: async () => {},
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const f of ['terminal-background-opacity.js', 'terminal-background-contrast.js', 'terminal-background-manifest.js', 'terminal-background.js']) {
        vm.runInContext(js(f), sandbox, { filename: f });
    }
    const bg = sandbox.TerminalBackground;
    Object.assign(bg.getOverrides(), { s: { theme_id: null, dim: null, disabled: false, image: 's.png' } });
    const client = { _containerEl: () => host, _currentTmuxName: () => 's', _session: 's', _xtermOpacity: sandbox.TerminalBackgroundOpacity.attach({ options: { theme: null } }) };
    bg.registerSurface(client);
    bg.setActiveSession('s');
    return { bg, revoked, host };
}

const tick = () => new Promise((r) => setImmediate(r));

test('uploading a new picture revokes the cached blob and paints the new bytes', async () => {
    const { bg, revoked, host } = setup();
    bg.repaint();
    await tick();
    assert.match(host.style.backgroundImage, /blob:1/, 'the first picture is painted from its blob');
    await bg.uploadImage('s', {});
    await tick();
    assert.deepEqual(revoked, ['blob:1'], 'the stale blob is released');
    assert.match(host.style.backgroundImage, /blob:2/, 'the new bytes are painted');
});

test('clearing the picture revokes the cached blob', async () => {
    const { bg, revoked } = setup();
    bg.repaint();
    await tick();
    await bg.clearImage('s');
    assert.deepEqual(revoked, ['blob:1']);
});

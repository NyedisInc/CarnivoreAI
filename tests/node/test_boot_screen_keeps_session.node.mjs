
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const ROUTER_SRC = fs.readFileSync(process.argv[2] || path.join(ROOT, 'client/js/router.js'), 'utf8');
const NAVGEN_SRC = fs.readFileSync(path.join(ROOT, 'client/js/navigation-generation.js'), 'utf8');

function load() {
    let announced = 0;
    const w = {
        location: { pathname: '/', search: '', hash: '' },
        addEventListener() {},
        dispatchEvent: () => true,
        AppBootComplete: { announce: () => { announced += 1; } },
    };
    w.window = w;
    w.history = { pushState() {}, replaceState() {} };
    const box = {
        window: w,
        document: { getElementById: () => null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout: () => 0,
        clearTimeout() {},
        Promise,
        CustomEvent: class {},
    };
    vm.createContext(box);
    vm.runInContext(NAVGEN_SRC, box);
    vm.runInContext(ROUTER_SRC, box);
    return { router: w.Router, announced: () => announced };
}

test('bootScreen leaves a session that is already on screen alone, and still announces the boot', () => {
    const { router, announced } = load();
    let launchpad = 0;
    router.bootScreen({ currentScreen: 'terminal', showLaunchpad: () => { launchpad += 1; } });
    assert.equal(launchpad, 0);
    assert.equal(announced(), 1);
});

test('control: bootScreen paints home on a plain boot with no screen up', () => {
    const { router } = load();
    let launchpad = 0;
    router.bootScreen({ currentScreen: null, showLaunchpad: () => { launchpad += 1; } });
    assert.equal(launchpad, 1);
});

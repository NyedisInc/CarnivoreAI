// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const BOOT_SRC = read('client/js/slash-commands-boot.js');
const NAVGEN_SRC = read('client/js/navigation-generation.js');
const APP_SRC = read('client/js/app.js') + read('client/js/app-screen-entry.js');
const CREATE_FLOW_SRC = read('web/src/lib/launchpad/create-flow.ts');
const NAVIGATION_SRC = read('web/src/lib/launchpad/navigation.ts');
const INDEX_HTML = read('client/index.html');

function makeRealm() {
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        Promise, setTimeout,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(NAVGEN_SRC, sandbox, { filename: 'navigation-generation.js' });
    vm.runInContext(BOOT_SRC, sandbox, { filename: 'slash-commands-boot.js' });

    const modal = {
        loaded: false,
        inits: [],
        inserted: [],
        init(cb, dir) {
            modal.onSelect = cb;
            return new Promise((resolve, reject) => {
                modal.inits.push({
                    dir,
                    resolve: () => { modal.loaded = true; resolve(); },
                    reject,
                });
            });
        },
    };
    sandbox.window.SlashCommandsModal = modal;
    sandbox.window.TerminalController = {
        inserted: [],
        insertText(text, ticket) { this.inserted.push([text, ticket]); },
    };
    return {
        window: sandbox.window,
        modal,
        Boot: sandbox.window.SlashCommandsBoot,
        NavGen: sandbox.window.NavigationGeneration,
    };
}

const settle = () => new Promise((r) => setTimeout(r, 0));


test('start() returns immediately, before the fetch has resolved', () => {
    const { Boot, modal } = makeRealm();
    assert.equal(Boot.start('/proj'), undefined,
        'start must return nothing, or somebody will await it');
    assert.equal(modal.inits.length, 1, 'the fetch did begin');
    assert.equal(Boot.state().loading, true, 'and it is still in flight');
});

test('the palette is recorded as loaded once its fetch lands', async () => {
    const { Boot, modal } = makeRealm();
    Boot.start('/proj');
    modal.inits[0].resolve();
    await settle();
    assert.equal(Boot.state().loadedFor, '/proj');
    assert.equal(Boot.state().loading, false);
});


test('THE SHOW GATE IS GONE BECAUSE THE THING IT GATED IS GONE', () => {
    // real.
    // there is nothing
    // guard.
    const code = BOOT_SRC.replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');
    assert.ok(code.length > 1000, 'the strip must not have emptied the file');
    assert.ok(!/showIfCurrent/.test(code),
        'the show gate must be deleted, not left as a no-op');
    assert.ok(!/modal\.show\(/.test(code),
        'nothing here reveals a control any more');
    assert.match(BOOT_SRC, /function start\(workingDir\) \{/,
        'and the parameter went with it');
    const modalSrc = read('client/js/slash-commands.js');
    assert.match(modalSrc, /TerminalInputOwnership\s*\n?\s*\?\s*window\.TerminalInputOwnership\.claim\('command'\)/,
        'open() must still claim ownership at the gesture');
});


test('re-entering the SAME project does not re-fetch', async () => {
    const { Boot, modal } = makeRealm();
    Boot.start('/proj');
    modal.inits[0].resolve();
    await settle();
    Boot.start('/proj');
    await settle();
    assert.equal(modal.inits.length, 1, 'one fetch for one project');
});

test('a DIFFERENT project does re-fetch, because its command set differs', async () => {
    const { Boot, modal } = makeRealm();
    Boot.start('/project-a');
    modal.inits[0].resolve();
    await settle();
    Boot.start('/project-b');
    await settle();
    assert.equal(modal.inits.length, 2);
    assert.equal(modal.inits[1].dir, '/project-b');
});

test('a second call while one is in flight JOINS it', async () => {
    const { Boot, modal } = makeRealm();
    Boot.start('/proj');
    Boot.start('/proj');
    Boot.start('/proj');
    assert.equal(modal.inits.length, 1, 'one fetch, not three');
    modal.inits[0].resolve();
    await settle();
    assert.equal(Boot.state().loadedFor, '/proj', 'and the one fetch answers all three');
});

test('A FAILED FETCH IS NOT CACHED AS AN ANSWER', async () => {
    const { Boot, modal } = makeRealm();
    Boot.start('/proj');
    modal.inits[0].reject(new Error('the server was not there'));
    await settle();
    assert.equal(Boot.state().loadedFor, null, 'a failure is not a loaded palette');
    Boot.start('/proj');
    assert.equal(modal.inits.length, 2, 'the next entry tries again');
});

test('a picked command reaches the terminal with its ownership ticket', async () => {
    const { Boot, modal, window: w } = makeRealm();
    Boot.start('/proj');
    modal.inits[0].resolve();
    await settle();
    const ticket = { claimed: 'at the gesture' };
    modal.onSelect('/clear', ticket);
    assert.deepEqual(w.TerminalController.inserted, [['/clear', ticket]]);
});


test('app.js no longer AWAITS the palette above the connect', () => {
    assert.ok(!/await window\.SlashCommandsModal\.init/.test(APP_SRC),
        'the terminal connect must not wait for the command list');
    const starts = (APP_SRC.match(/SlashCommandsBoot\.start\(/g) || []).length;
    assert.equal(starts, 1,
        `the one shared entry body must start it; found ${starts}`);
    assert.ok(!/SlashCommandsBoot\.start\([^)]*,\s*nav\)/.test(APP_SRC),
        'neither may still hand it a navigation token: the gate it fed is gone');
});

test('index.html serves the boot module after the modal it drives', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const boot = order.indexOf('slash-commands-boot.js');
    assert.ok(boot >= 0, 'the module must be in index.html or it is dead code');
    assert.ok(order.indexOf('slash-commands.js') < boot);
    assert.ok(order.indexOf('navigation-generation.js') < boot);
});


test('THE CREATE PATH ENTERS THE SESSION BEFORE IT REPAINTS THE LIST', () => {
    const fn = CREATE_FLOW_SRC.slice(CREATE_FLOW_SRC.indexOf('export async function createProjectFlow('));
    const body = fn.slice(0, fn.indexOf('isAlreadyRunning(error)'));
    const enter = body.indexOf('host.announceSessionCreated(session, nav)');
    const decorate = body.lastIndexOf('await refreshProjects(host)');
    assert.ok(enter > 0 && decorate > 0, 'both steps must still happen');
    assert.ok(enter < decorate,
        'the user watches a list repaint before their new session appears');
});

test('the decoration still happens, and is still guarded on its own', () => {
    const fn = CREATE_FLOW_SRC.slice(CREATE_FLOW_SRC.indexOf('export async function createProjectFlow('));
    const body = fn.slice(0, fn.indexOf('isAlreadyRunning(error)'));
    assert.ok(body.includes('await refreshProjects(host)'));
    const helper = CREATE_FLOW_SRC.slice(CREATE_FLOW_SRC.indexOf('async function refreshProjects('));
    assert.ok(/catch/.test(helper.slice(0, helper.indexOf('\n}'))),
        'a failed repaint must not read as a failed create');
});

test('CreateSessionRequest.label is still sent', () => {
    const fn = CREATE_FLOW_SRC.slice(CREATE_FLOW_SRC.indexOf('export function buildCreatePayload('));
    const body = fn.slice(0, fn.indexOf('\n}'));
    assert.ok(/label:/.test(body), 'the launch must still name the session');
});


test('NEITHER detach path sleeps before it acts', () => {
    assert.match(NAVIGATION_SRC, /export const DETACH_SETTLE_MS = 0;/,
        'a detach settle delay is back; the awaited detach response is the '
        + 'completion signal, so a sleep here waits for what already happened');
    for (const name of ['detachAndOpenProject', 'detachAndCreateNew']) {
        const fn = NAVIGATION_SRC.slice(NAVIGATION_SRC.indexOf(`export async function ${name}(`));
        const body = fn.slice(0, fn.indexOf('\n}'));
        assert.ok(!/setTimeout/.test(body),
            `${name} still sleeps before re-opening`);
        assert.ok(/await host\.detachSession\(\)/.test(body),
            `${name} must still wait for the detach itself`);
    }
});

test('and each reports its OWN failure rather than calling it a failed detach', () => {
    const fn = NAVIGATION_SRC.slice(NAVIGATION_SRC.indexOf('export async function detachAndOpenProject('));
    const body = fn.slice(0, fn.indexOf('\n}'));
    assert.equal((body.match(/catch \(error\)/g) || []).length, 2,
        'the detach and the re-open are two failures and need two messages');
    assert.ok(body.includes('HOME_KEYS.openFailed'), 'the re-open names itself');
});

test('no 500ms sleep survives anywhere on the launch or connect paths', () => {
    for (const rel of ['web/src/lib/launchpad/navigation.ts',
        'web/src/lib/launchpad/create-flow.ts', 'client/js/terminal.js',
        'client/js/app.js']) {
        const src = read(rel);
        assert.ok(!/setTimeout\([^;]*,\s*500\s*\)/.test(src),
            `${rel} still carries a 500ms delay`);
    }
});

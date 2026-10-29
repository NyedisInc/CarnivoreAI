import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createI18n } from '../client/js/i18n/runtime.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const clientJs = (f) => fs.readFileSync(path.join(__dirname, '..', 'client', 'js', f), 'utf8');

let passes = 0;
let failures = 0;
const queue = [];
const test = (name, fn) => queue.push([name, fn]);

function realm(files, extra = {}) {
    const context = { console, CloudeI18n: createI18n(), ...extra };
    context.globalThis = context;
    context.window = context;
    context.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
    context.dispatchEvent = (ev) => { (context.events = context.events || []).push(ev.type); (context.details = context.details || []).push(ev.detail); };
    vm.createContext(context);
    for (const f of files) vm.runInContext(clientJs(f), context);
    return context;
}

const REC = (over = {}) => ({
    session_uuid: 'u-a', tmux_name: 'carnivore_a', tmux_created_epoch: 100,
    title: 'fix the deploy', asleep: true, archived_at: null, owned: true, ...over,
});

test('kill draws a skull, sleep a moon, wake a sun: three distinct glyphs', () => {
    const w = realm(['session-row-menu-icons.js']);
    const kill = w.SessionRowMenuIcons.svg('close');
    const sleep = w.SessionRowMenuIcons.svg('sleep');
    const wake = w.SessionRowMenuIcons.svg('wake');
    for (const g of [kill, sleep, wake]) assert.match(g, /<svg [^>]*><(path|circle)/);
    assert.equal(new Set([kill, sleep, wake]).size, 3);
    assert.ok(!kill.includes('M4 4l8 8'), 'kill still draws the old X');
});

test('the shared status light draws an asleep row as the moon, not a dot', () => {
    const w = realm(['status-led.js', 'session-status-ui.js']);
    const html = w.SessionStatusUI.dotHtml('asleep', { transport: 'disconnected' });
    assert.match(html, /data-inner="asleep"/, 'asleep must outrank a missing socket');
    assert.match(html, /status-dot--asleep/);
    assert.match(html, /aria-label="asleep - /);
    assert.doesNotMatch(w.SessionStatusUI.dotHtml('idle', {}), /asleep/);
    const css = fs.readFileSync(path.join(__dirname, '..', 'client', 'css', 'status-led.css'), 'utf8');
    assert.match(css, /\.status-led\[data-inner='asleep'\]::after[^{]*\{[^}]*mask-image/);
});

test('a flagged asleep row is the moon in the unread colour, and says so (issue #749)', () => {
    const w = realm(['status-led.js', 'session-status-ui.js']);
    const flagged = w.SessionStatusUI.dotHtml('asleep', { unread: true, transport: 'disconnected' });
    assert.match(flagged, /data-inner="asleep-unread"/);
    assert.match(flagged, /data-outer="off"/, 'no ring around the moon');
    assert.match(flagged, /status-dot--asleep/, 'still the asleep status');
    assert.match(flagged, /aria-label="asleep, flagged unread - wake it to follow up"/);
    assert.match(flagged, /title="asleep, flagged unread - wake it to follow up"/);
    const plainMoon = w.SessionStatusUI.dotHtml('asleep', { unread: false });
    assert.match(plainMoon, /data-inner="asleep"/);
    assert.doesNotMatch(plainMoon, /flagged/);
    assert.match(w.SessionStatusUI.dotHtml('idle', { unread: true }), /data-outer="unread"/);
    const css = fs.readFileSync(path.join(__dirname, '..', 'client', 'css', 'status-led.css'), 'utf8');
    assert.match(css, /\.status-led\[data-inner='asleep-unread'\] \{\s*--led-ink: var\(--led-color-unread\);/,
        'the unread moon is inked with the unread token, no literal colour');
    assert.match(css, /\.status-led\[data-inner='asleep-unread'\]::after \{[^}]*mask-image/,
        'the unread moon wears the same moon mask');
});

function runner(answer) {
    const calls = [];
    const said = [];
    const w = realm(['session-row-menu-sleep.js'], {
        API: {
            sleepSession: async (u) => { calls.push(['sleep', u]); return answer; },
            wakeSession: async (u) => { calls.push(['wake', u]); return answer; },
        },
        SessionRowMenuActions: { say: (ctx, text) => said.push(text) },
        SessionSidebar: { _activeTmuxName: 'carnivore_a', _fetchAndRender: async () => {} },
        TerminalController: { sessionActive: true, ws: { close() { this.closed = true; } } },
    });
    return { w, calls, said };
}

test('sleep sends the uuid, and a refusal shows the server sentence', async () => {
    const { w, calls, said } = runner({ status: 'refused', detail: 'cannot sleep: no conversation id' });
    await w.SessionRowMenuSleep.runSleep({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.deepEqual(calls, [['sleep', 'u-a']]);
    assert.equal(said.length, 1);
    assert.ok(said[0].includes('cannot sleep: no conversation id'));
    assert.equal(w.TerminalController.sessionActive, true, 'a refused sleep leaves this tab alone');
});

test('sleeping the session this tab shows releases the tab without reconnecting', async () => {
    const { w, said } = runner({ status: 'asleep', detail: 'asleep' });
    await w.SessionRowMenuSleep.runSleep({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.deepEqual(said, []);
    assert.equal(w.TerminalController.sessionActive, false);
    assert.equal(w.TerminalController._intentionalClose, true);
    assert.deepEqual(w.events, ['cloude:primary-session-gone']);
    assert.equal(w.details.length === 1 && w.details[0].tmuxName, 'carnivore_a', 'the event names the session that went (last-view forgets by identity)');
});

test('wake sends the uuid and stays quiet when it started', async () => {
    const { w, calls, said } = runner({ status: 'started' });
    await w.SessionRowMenuSleep.runWake({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.deepEqual(calls, [['wake', 'u-a']]);
    assert.deepEqual(said, []);
});

function pickerRunner(pick, lastError = '') {
    const calls = [];
    const said = [];
    const opened = [];
    const w = realm(['session-row-menu-sleep.js'], {
        API: {
            wakeSession: async (u, agent) => {
                calls.push(['wake', u, agent]);
                return agent
                    ? { status: 'started', detail: 'resumed' }
                    : { status: 'refused', code: 'wrapper_needed', detail: "'claude' is not a configured launch wrapper",
                        wrapper_options: ['claude-skip-permissions', 'keyc'] };
            },
        },
        SessionRestartPicker: {
            open: async (...args) => { opened.push(args); return pick; },
            lastError: () => lastError,
        },
        SessionRowMenuActions: { say: (ctx, text) => said.push(text) },
        SessionSidebar: { _activeTmuxName: null, _fetchAndRender: async () => {} },
    });
    return { w, calls, said, opened };
}

test('wrapper_needed opens the restart picker and wakes again with the pick', async () => {
    const { w, calls, said, opened } = pickerRunner({ agentType: 'claude-skip-permissions', mode: 'recreate' });
    await w.SessionRowMenuSleep.runWake({ name: 'carnivore_3D Studio-2', label: '3D Studio', sessionUuid: 'u-3d' });
    assert.deepEqual(opened, [['carnivore_3D Studio-2', '3D Studio', null, 'u-3d']],
        'the picker gets the uuid, so it asks the recreate preview for a row with no tmux');
    assert.deepEqual(calls, [['wake', 'u-3d', undefined], ['wake', 'u-3d', 'claude-skip-permissions']]);
    assert.deepEqual(said, [], 'a wake that started says nothing');
});

test('the account the picker returned reaches the wake call (#1641)', async () => {
    const seen = [];
    const w = realm(['session-row-menu-sleep.js'], {
        API: { wakeSession: async (u, agent, account) => { seen.push([u, agent, account]); return { status: 'started' }; } },
        SessionRestartPicker: { open: async () => ({ agentType: 'keyc', mode: 'recreate', account: { accountId: 'play', pinned: true } }), lastError: () => '' },
    });
    await w.SessionRowMenuSleep.pickAndWake('carnivore_a', 'a', 'u-a');
    assert.deepEqual(JSON.parse(JSON.stringify(seen)), [['u-a', 'keyc', { accountId: 'play', pinned: true }]]);
});

test('cancelling the picker wakes nothing and says nothing', async () => {
    const { w, calls, said } = pickerRunner(null);
    await w.SessionRowMenuSleep.runWake({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.equal(calls.length, 1, 'no second wake after a cancel');
    assert.deepEqual(said, []);
});

test('a picker that could not load says why instead of going quiet', async () => {
    const { w, said } = pickerRunner(null, 'preview failed: 503');
    await w.SessionRowMenuSleep.runWake({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.equal(said.length, 1);
    assert.ok(said[0].includes('preview failed: 503'));
});

test('any other refusal still shows the server sentence, no picker', async () => {
    const { w, said, opened } = pickerRunner(null);
    w.API.wakeSession = async () => ({ status: 'refused', detail: 'its transcript is gone' });
    await w.SessionRowMenuSleep.runWake({ name: 'carnivore_a', sessionUuid: 'u-a' });
    assert.deepEqual(opened, []);
    assert.ok(said[0].includes('its transcript is gone'));
});

for (const [name, fn] of queue) {
    try { await fn(); console.log(`ok - ${name}`); passes++; }
    catch (err) { console.log(`NOT OK - ${name}`); console.error(err); failures++; }
}
console.log(`${passes} passed, ${failures} failed`);
if (failures || passes === 0) process.exit(1);

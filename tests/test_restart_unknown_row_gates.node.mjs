
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { fakeHandle } from './helpers/launch_choice_fake.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function attrsOf(tag) {
    const out = new Map();
    const body = tag.replace(/^<\w+/, '').replace(/>$/, '');
    const re = /([\w-]+)(?:="([^"]*)")?/g;
    let m;
    while ((m = re.exec(body)) !== null) out.set(m[1], m[2] == null ? '' : m[2]);
    return out;
}

function fakeEl(attrs) {
    const listeners = {};
    return {
        attrs,
        id: attrs.get('id') || '',
        value: attrs.get('value') || '',
        checked: attrs.has('checked'),
        disabled: attrs.has('disabled'),
        textContent: '',
        classList: { toggle() {} },
        parentNode: { classList: { toggle() {} } },
        getAttribute(n) { return attrs.has(n) ? attrs.get(n) : null; },
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        fire(type, ev) { (listeners[type] || []).forEach((fn) => fn(ev || {})); },
        focus() {},
    };
}

function fakeOverlay() {
    const listeners = {};
    const overlay = {
        className: '',
        els: [],
        set innerHTML(html) {
            this.els = (html.match(/<(input|button|div)\b[^>]*>/g) || [])
                .map((t) => fakeEl(attrsOf(t)));
        },
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        fire(type) { (listeners[type] || []).forEach((fn) => fn({ target: null })); },
        querySelector(sel) {
            if (sel.startsWith('#')) return this.els.find((e) => e.id === sel.slice(1)) || null;
            throw new Error(`unhandled selector ${sel}`);
        },
    };
    return overlay;
}

function load(confirmAnswer) {
    const overlays = [];
    const confirms = [];
    const sandbox = {
        console: { log() {}, error() {}, warn() {} },
        document: {
            createElement() { return fakeOverlay(); },
            body: { appendChild(el) { overlays.push(el); } },
        },
    };
    sandbox.window = sandbox;
    sandbox.SessionSidebarRowControls = {
        escHtml: (v) => String(v == null ? '' : v).replace(/&/g, '&amp;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
    };
    const handles = [];
    sandbox.CloudeWeb = {
        mountLaunchChoice(_id, opts) {
            const handle = fakeHandle(opts.rows, opts.value);
            handles.push(handle);
            return handle;
        },
    };
    sandbox.App = {
        showConfirmModal(...args) {
            confirms.push(args);
            return Promise.resolve(confirmAnswer);
        },
    };
    vm.createContext(sandbox);
    for (const name of ['session-status-ui.js',
        'session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']) {
        vm.runInContext(fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js', name), 'utf8'), sandbox);
    }
    return { w: sandbox.window, overlays, confirms, handles };
}

function preview(paneState) {
    const readable = paneState !== 'unknown';
    return {
        name: 'cloude_wedged',
        current_agent_type: 'codex',
        pane_state: paneState,
        unchanged: readable
            ? { kind: 'not_dead', detail: 'this session is still running', actionable: false }
            : { kind: 'cannot_determine', detail: 'tmux did not answer', actionable: false },
        projected: readable
            ? { kind: 'agent', detail: 'restarting the agent', actionable: true }
            : { kind: 'cannot_determine', detail: 'tmux did not answer', actionable: false },
        options: [],
        wrappers_status: 'ok',
    };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

async function scenario(status, paneState, confirmAnswer, arm) {
    const { w, overlays, confirms } = load(confirmAnswer);
    let settled = false;
    let result;
    w.SessionRestartPicker.present('wedged', preview(paneState), status, 'restart', null)
        .then((v) => { settled = true; result = v; });
    const overlay = overlays[0];
    const go = overlay.querySelector('#restart-picker-go');
    const box = overlay.querySelector('#restart-picker-live');
    const goDisabledBefore = go.disabled;
    if (arm && box) {
        box.checked = true;
        overlay.fire('change');
    }
    go.fire('click');
    await tick();
    await tick();
    return { result, confirms, goDisabledBefore, armPresent: !!box, settled, goDisabledAfter: go.disabled };
}

const results = [];
async function test(name, fn) {
    try {
        await fn();
        results.push(true);
        console.log(`ok - ${name}`);
    } catch (err) {
        results.push(false);
        console.log(`not ok - ${name}\n    ${err && err.message}`);
    }
}

for (const status of ['unknown', 'working']) {
    await test(`[${status}] a measured-alive pane renders the arm box, and unarmed nothing is sendable`, async () => {
        const r = await scenario(status, 'alive', true, false);
        assert.equal(r.armPresent, true, 'no arm box over a measured-alive pane');
        assert.equal(r.goDisabledBefore, true, 'the restart button was enabled before arming');
        assert.equal(r.confirms.length, 0, 'a confirm was asked without arming');
        assert.equal(r.settled, false, 'the panel resolved from an unarmed click');
    });

    await test(`[${status}] armed, the click restarts at once with no confirm modal`, async () => {
        const r = await scenario(status, 'alive', false, true);
        assert.equal(r.goDisabledAfter, false, 'arming did not enable the button');
        assert.equal(r.confirms.length, 0, 'a confirm modal was shown after the armed click');
        assert.equal(r.settled, true, 'the armed click did not resolve the panel');
        assert.equal(r.result.confirmRestartLive, true);
        assert.equal(r.result.mode, 'restart');
    });

    await test(`[${status}] a pane tmux could not read gets no arm box and nothing enabled`, async () => {
        const r = await scenario(status, 'unknown', true, true);
        assert.equal(r.armPresent, false, 'an unreadable pane was offered the arm box');
        assert.equal(r.goDisabledBefore, true, 'an unreadable pane enabled the button');
        assert.equal(r.confirms.length, 0);
        assert.equal(r.settled, false);
    });
}


async function drive(pv, arm, account) {
    const { w, overlays, handles } = load(true);
    let settled = false;
    let result;
    w.SessionRestartPicker.present('wedged', pv, 'working', 'restart', null)
        .then((v) => { settled = true; result = v; });
    const overlay = overlays[0];
    const handle = handles[0];
    handle.state.answer = account;
    const go = overlay.querySelector('#restart-picker-go');
    const box = overlay.querySelector('#restart-picker-live');
    if (arm && box) { box.checked = true; overlay.fire('change'); }
    go.fire('click');
    await tick();
    return { get result() { return result; }, settled, go, handle, box };
}

await test('GATE 1: a live row stays refused by the handle until the arm box is ticked, then only a live-eligible one opens', async () => {
    const live = preview('alive');
    const r0 = await drive(live, false, null);
    assert.equal(r0.handle.selected().disabled, true, 'a live row was choosable with the box unticked');
    assert.equal(r0.go.disabled, true);
    assert.equal(r0.settled, false);
    const r1 = await drive(live, true, null);
    assert.equal(r1.handle.selected().disabled, false, 'ticking the box did not release a live-eligible row');
    for (const kind of ['cannot_determine', 'transcript_missing']) {
        const bad = preview('alive');
        bad.projected = { kind, detail: 'x', actionable: false };
        const r = await drive(bad, true, null);
        assert.equal(r.handle.selected().disabled, true, `${kind} became choosable by arming`);
        assert.equal(r.go.disabled, true, `${kind}: the button opened`);
        assert.equal(r.settled, false, `${kind}: a restart fired`);
    }
});

await test('GATE 2: confirmRestartLive comes from the box alone, and the account answer rides along', async () => {
    const account = { accountId: 'play', pinned: true };
    const armed = await drive(preview('alive'), true, account);
    assert.equal(armed.settled, true);
    assert.equal(armed.result.confirmRestartLive, true);
    assert.deepEqual(armed.result.account, account);
    const dead = preview('dead');
    dead.unchanged = { kind: 'agent', detail: 'restarting', actionable: true };
    dead.projected = { kind: 'agent', detail: 'restarting', actionable: true };
    const calm = await drive(dead, false, null);
    assert.equal(calm.box, null, 'a dead pane got an arm box');
    assert.equal(calm.settled, true, 'a dead actionable pane could not be restarted');
    assert.equal(calm.result.confirmRestartLive, false, 'a dead restart claimed it was armed');
    assert.equal(calm.result.account, null);
});

await test('GATE 3: no compiled control means nothing is pickable and the click does nothing', async () => {
    const { w, overlays } = load(true);
    w.CloudeWeb = {};
    let settled = false;
    w.SessionRestartPicker.present('wedged', preview('alive'), 'working', 'restart', null).then(() => { settled = true; });
    const go = overlays[0].querySelector('#restart-picker-go');
    const box = overlays[0].querySelector('#restart-picker-live');
    box.checked = true;
    overlays[0].fire('change');
    assert.equal(go.disabled, true, 'a restart was enabled with no choice drawn');
    go.fire('click');
    await tick();
    assert.equal(settled, false);
});

await test('the pure gate: only the server permission, or a ticked box with a live-eligible row, opens a row', () => {
    const { w } = load(true);
    const gate = w.SessionRestartPicker.rowEnabled;
    assert.equal(gate({ 'actionable-now': '1' }, false), true);
    assert.equal(gate({ 'actionable-now': '0', 'live-eligible': '1' }, false), false);
    assert.equal(gate({ 'actionable-now': '0', 'live-eligible': '1' }, true), true);
    assert.equal(gate({ 'actionable-now': '0', 'live-eligible': '0' }, true), false);
    assert.equal(gate({ 'actionable-now': '0', 'live-eligible': '1' }, 'yes'), false, 'a truthy non-boolean armed the gate');
    assert.equal(gate({}, true), false);
    assert.equal(gate(undefined, true), false);
});

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('ALL PASS');

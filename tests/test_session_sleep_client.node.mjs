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


for (const [name, fn] of queue) {
    try { await fn(); console.log(`ok - ${name}`); passes++; }
    catch (err) { console.log(`NOT OK - ${name}`); console.error(err); failures++; }
}
console.log(`${passes} passed, ${failures} failed`);
if (failures || passes === 0) process.exit(1);

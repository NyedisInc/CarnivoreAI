
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(__dirname, '..', 'client', 'js');

const { iconSvg } = await import(pathToFileURL(path.join(JS, 'icons', 'icon-registry.js')).href);

function load(files, withGlyphs = true, setup = () => {}) {
    const window = {};
    if (withGlyphs) window.CloudeGlyphs = { iconSvg };
    setup(window);
    const ctx = { window, globalThis: window, console: { log() {}, error() {} } };
    window.window = window;
    vm.createContext(ctx);
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(JS, f), 'utf8'), ctx);
    return window;
}

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

const w = load(['agent-family-icon.js', 'wrapper-mark.js']);

test('a picked icon draws the icon registry glyph, not the family mark', () => {
    const got = w.WrapperMark.svg({ icon: 'globe', family: 'claude' }, 14);
    assert.equal(got, iconSvg('globe', 14));
    assert.notEqual(got, w.AgentFamilyIcon.svg('claude', 14));
    assert.equal(w.WrapperMark.source({ icon: 'globe', family: 'claude' }), 'icon');
});

test('no icon draws the family mark', () => {
    for (const icon of [null, undefined, '']) {
        assert.equal(w.WrapperMark.svg({ icon, family: 'codex' }, 14), w.AgentFamilyIcon.svg('codex', 14));
        assert.equal(w.WrapperMark.source({ icon, family: 'codex' }), 'family');
    }
});

test('an id this build does not know falls back to the family mark', () => {
    assert.equal(iconSvg('from-the-future', 14), '');
    assert.equal(w.WrapperMark.svg({ icon: 'from-the-future', family: 'claude' }, 14), w.AgentFamilyIcon.svg('claude', 14));
    assert.equal(w.WrapperMark.source({ icon: 'from-the-future', family: 'claude' }), 'family');
});

test('a hostile id is only a lookup key, never markup', () => {
    const got = w.WrapperMark.svg({ icon: '"><script>x</script>', family: 'claude' }, 14);
    assert.equal(got, w.AgentFamilyIcon.svg('claude', 14));
    assert.ok(!got.includes('script'));
});

test('without the glyph boot the family mark still draws', () => {
    const bare = load(['agent-family-icon.js', 'wrapper-mark.js'], false);
    assert.equal(bare.WrapperMark.svg({ icon: 'globe', family: 'claude' }, 14), bare.AgentFamilyIcon.svg('claude', 14));
});

test('the restart and wake picker hands each option its icon and family for the compiled mark', () => {
    const r = load(['agent-family-icon.js', 'wrapper-mark.js', 'session-restart-options.js'], true, (win) => {
        win.SessionSidebarRowControls = { escHtml: (v) => String(v == null ? '' : v) };
    });
    const rows = r.SessionRestartOptions.optionRows({
        unchanged: { kind: 'agent', actionable: true },
        projected: { kind: 'agent' },
        options: [
            { agent_type: 'claude-chrome', label: 'chrome', family: 'claude', icon: 'globe', kind: 'agent', actionable_now: true },
            { agent_type: 'codex-yolo', label: 'yolo', family: 'codex', icon: null, kind: 'agent', actionable_now: true },
            { agent_type: 'old-server', label: 'old', kind: 'agent', actionable_now: true },
        ],
    });
    assert.equal(rows.length, 4);
    assert.deepEqual([rows[0].harness, rows[0].icon], ['', null], 'the "as launched" row carries no mark facts');
    assert.deepEqual([rows[1].harness, rows[1].icon], ['claude', 'globe']);
    assert.deepEqual([rows[2].harness, rows[2].icon], ['codex', null]);
    assert.deepEqual([rows[3].harness, rows[3].icon], ['', null], 'an option from an older server carries none');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);

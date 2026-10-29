
import assert from 'node:assert/strict';
import { Doc, fakeStorage, loadModules, results, test } from './lib-sidebar-sessions.mjs';

function load() {
    return loadModules([
        'status-led.js', 'session-model-icon.js', 'agent-family-icon.js',
        'sidebar-help.js',
    ], { storage: fakeStorage({}), document: new Doc() }).window;
}

await test('one row per distinct light, each drawn by StatusLed', () => {
    const w = load();
    const pairs = w.SidebarHelp.LIGHTS.map((l) => `${l.inner}/${l.outer}`);
    assert.equal(new Set(pairs).size, pairs.length, 'no two rows draw the same light');
    assert.equal(pairs.length, 7);
    const html = w.SidebarHelp.panelHtml();
    for (const l of w.SidebarHelp.LIGHTS) {
        assert.ok(html.includes(`data-inner="${l.inner}" data-outer="${l.outer}"`), `${l.inner}/${l.outer} drawn`);
    }
});

await test('the robot ladder reads from the thresholds', () => {
    const w = load();
    const H = w.SidebarHelp;
    assert.equal(H.tierRange(1), 'under $2');
    assert.equal(H.tierRange(2), '$2 to under $8');
    assert.equal(H.tierRange(4), '$16 to under $32');
    assert.equal(H.tierRange(5), '$32 and up');
    const html = H.panelHtml();
    for (let t = 1; t <= 5; t++) assert.ok(html.includes(`data-model-tier="${t}"`), `tier ${t} robot drawn`);
    assert.ok(html.includes('data-model-top="1"'), 'the topped robot is drawn');
    assert.ok(html.includes('data-model-tier=""'), 'the unpriced robot is drawn');
});

await test('the copy is lowercase and carries no dashes or emoji', () => {
    const w = load();
    const text = w.SidebarHelp.panelHtml().replace(/<[^>]*>/g, ' ');
    assert.doesNotMatch(text, /[\u2013\u2014]/);
    assert.doesNotMatch(text, /[\u{1F300}-\u{1FAFF}]/u);
});

await test('the header now carries its own X, alongside the footer close', () => {
    const html = load().SidebarHelp.panelHtml();
    assert.ok(html.includes('id="sidebar-help-header-close"'), 'the header X is drawn');
    assert.ok(/class="modal-close" id="sidebar-help-header-close"/.test(html), 'it wears the shared modal-close look');
    assert.ok(html.includes('id="sidebar-help-close"'), 'the pre-existing footer close is untouched');
});

await test('the legend carries the pinned and not pinned rows', () => {
    const w = load();
    w.SessionSidebarRowControls = {
        escAttr: (v) => String(v), escHtml: (v) => String(v),
        pinLegendHtml: (pinned) => `<button class="session-sidebar-row-pin" aria-pressed="${pinned}"></button>`,
    };
    const html = w.SidebarHelp.panelHtml();
    assert.ok(html.includes('pinned: kept at the top of the list'), 'pinned row');
    assert.ok(html.includes('not pinned (tilted). click it to pin'), 'not pinned row');
    assert.ok(html.includes('aria-pressed="true"') && html.includes('aria-pressed="false"'), 'both swatches drawn');
});


const { passes, failures } = results();
console.log(failures ? `${passes} passed, ${failures} failed` : 'ALL PASS');
process.exit(failures ? 1 : 0);

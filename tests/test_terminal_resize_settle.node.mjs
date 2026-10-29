
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const CLIENT = path.join(ROOT, 'client');

let failures = 0;
let passes = 0;

async function test(name, fn) {
    try {
        await fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function loadSettle() {
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(path.join(CLIENT, 'js', 'terminal-resize-settle.js'), 'utf8'),
        sandbox, { filename: 'terminal-resize-settle.js' });
    return sandbox.TerminalResizeSettle;
}


await test('positive control: the module loads', () => {
    const s = loadSettle();
    assert.ok(s, 'module did not attach - every assertion below is vacuous');
    assert.equal(s.SETTLE_MS, 500);
});

await test('an observer change settling back to the pane geometry is SKIPPED', () => {
    const s = loadSettle();
    assert.equal(s.decideResize({
        source: 'ResizeObserver', cols: 215, rows: 45, lastCols: 215, lastRows: 45,
    }), 'skip_transient');
});

await test('an observer change to a GENUINELY new geometry still ships', () => {
    const s = loadSettle();
    assert.equal(s.decideResize({
        source: 'ResizeObserver', cols: 215, rows: 41, lastCols: 215, lastRows: 45,
    }), 'ship', 'the observer is the safety net for real unannounced changes');
    assert.equal(s.decideResize({
        source: 'ResizeObserver', cols: 100, rows: 45, lastCols: 215, lastRows: 45,
    }), 'ship', 'a width-only change is a real change');
});

await test('ANNOUNCED resizes are never suppressed, even at identical dims', () => {
    const s = loadSettle();
    for (const source of ['window.resize', 'orientationchange',
        'visualViewport.resize', 'sidebar-pin', 'handshake', 'ws.onopen']) {
        assert.equal(s.decideResize({
            source, cols: 215, rows: 45, lastCols: 215, lastRows: 45,
        }), 'ship', `${source} is a deliberate act and must reach the pane`);
    }
});

await test('an unknown/untagged source is treated as observer-grade', () => {
    const s = loadSettle();
    assert.equal(s.decideResize({
        source: 'unknown', cols: 215, rows: 45, lastCols: 215, lastRows: 45,
    }), 'skip_transient',
    'defaulting an unrecognised tag to "announced" would reopen the hole');
});

await test('a first-ever fit ships - there is no previous geometry to match', () => {
    const s = loadSettle();
    assert.equal(s.decideResize({
        source: 'ResizeObserver', cols: 215, rows: 45,
        lastCols: undefined, lastRows: undefined,
    }), 'ship', 'tmux has never been told anything, so this cannot be a no-op');
});

await test('only unannounced sources wait the long settle window', () => {
    const s = loadSettle();
    assert.equal(s.settleMsFor('ResizeObserver', 100), 500,
        'the flap must resolve inside the window so it is never sampled mid-flap');
    assert.equal(s.settleMsFor('unknown', 100), 500);
    for (const source of ['window.resize', 'orientationchange',
        'visualViewport.resize', 'sidebar-pin', 'handshake', 'ws.onopen']) {
        assert.equal(s.settleMsFor(source, 100), 100,
            `${source} must stay responsive`);
    }
});

await test('the culprit description never throws and never blocks', () => {
    const s = loadSettle();
    assert.equal(s.describeCulprit(null), '');
    assert.equal(s.describeCulprit({}), '');
    const container = {
        children: [
            { tagName: 'DIV', id: 'terminal', className: '', style: {} },
            {
                tagName: 'DIV', id: 'localServersContainer',
                className: 'local-servers', style: { display: 'block' },
            },
            {
                tagName: 'DIV', id: 'hidden', className: 'x',
                style: { display: 'none' },
            },
        ],
    };
    assert.equal(s.describeCulprit(container),
        'div#localServersContainer.local-servers',
        'the log must name what was on screen, and skip #terminal itself');
});


function ruleBody(selector) {
    const css = fs.readFileSync(path.join(CLIENT, 'css', 'styles.css'), 'utf8');
    const i = css.indexOf(`\n${selector} {`);
    if (i === -1) return '';
    return css.slice(i, css.indexOf('\n}', i));
}

await test('.local-servers has no CSS rule any more', () => {
    assert.equal(ruleBody('.local-servers'), '',
        'the panel was removed; its CSS rule must not linger');
});

await test('#localServersContainer is gone from index.html, terminal container remains', () => {
    const html = fs.readFileSync(path.join(CLIENT, 'index.html'), 'utf8');
    assert.ok(html.indexOf('<div class="terminal-container"') > 0,
        'the terminal container itself must still be present');
    assert.equal(html.indexOf('id="localServersContainer"'), -1,
        'the panel markup was removed and must not reappear');
});

await test('the local-servers fetch/render methods are gone from terminal.js', () => {
    const src = fs.readFileSync(path.join(CLIENT, 'js', 'terminal.js'), 'utf8');
    for (const name of ['_renderLocalServers', 'loadLocalServers',
        '_mergeLocalServer', '_dropLocalServer', '_activeSessionName']) {
        assert.equal(src.indexOf(name), -1, `${name} must be fully removed`);
    }
});

await test('.terminal-container still fills the available height with nothing overlaid', () => {
    const body = ruleBody('.terminal-container');
    assert.ok(body.length > 0, '.terminal-container rule missing');
    assert.match(body, /flex:\s*1/,
        'the terminal container must still fill the space it is given');
});


await test('.info has no CSS rule any more, and neither does the token that reserved its height', () => {
    assert.equal(ruleBody('.info'), '', 'the bar was removed; its CSS rule must not linger');
    const css = fs.readFileSync(path.join(CLIENT, 'css', 'styles.css'), 'utf8');
    assert.doesNotMatch(css, /--terminal-bar-height/,
        'a token reserving space for a deleted bar is dead weight, not a harmless leftover');
});

await test('.info and its three late-populated children are gone from index.html', () => {
    const html = fs.readFileSync(path.join(CLIENT, 'index.html'), 'utf8');
    assert.equal(html.indexOf('<div class="info">'), -1,
        'the bar markup was removed and must not reappear');
    for (const id of ['sessionInfo', 'terminal-bar-status', 'terminal-bar-status-text']) {
        assert.equal(html.indexOf(`id="${id}"`), -1, `#${id} was removed and must not reappear`);
    }
});

await test('the bottom-bar watch is gone from terminal-layout.js - nothing left for it to watch', () => {
    const src = fs.readFileSync(path.join(CLIENT, 'js', 'terminal-layout.js'), 'utf8');
    assert.doesNotMatch(src, /watchBottomBar/, 'a watch over a deleted element is dead code');
    assert.doesNotMatch(src, /TERM-BAR/, 'its log tag must not linger either');
});


await test('index.html loads the guard BEFORE terminal-layout.js', () => {
    const html = fs.readFileSync(path.join(CLIENT, 'index.html'), 'utf8');
    const iGuard = html.indexOf('js/terminal-resize-settle.js');
    const iLayout = html.indexOf('js/terminal-layout.js');
    assert.ok(iGuard > 0, 'terminal-resize-settle.js is not served at all');
    assert.ok(iGuard < iLayout, 'must load before terminal-layout.js');
});

await test('terminal-layout.js actually consults the guard on both paths', () => {
    const src = fs.readFileSync(path.join(CLIENT, 'js', 'terminal-layout.js'), 'utf8');
    assert.match(src, /settleMsFor\(/, 'requestFit must ask how long to wait');
    assert.match(src, /skip_transient/, 'flush must honour the verdict');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
